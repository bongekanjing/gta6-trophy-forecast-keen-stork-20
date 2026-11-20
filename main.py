"""Forecast GTA VI trophy earn rates at a target instant, as five quantiles each.

The house records the same trophy page again and again, and the rate it prints
moves for three reasons: the tracked-player count changes, players who are
already tracked earn more trophies, and the page rounds to two decimals. This
deposit of 55 rates is what an entry has to beat, so the forecast is built from
what the history actually shows rather than from a story about trophy tiers:

  1. Measure the drift of each trophy's rate along its own recorded history, on
     the logit scale, where a miss from 1% to 2% costs what a miss from 33% to
     50% does. The scorer uses that scale, so the fit is done on it too.
  2. Shrink that drift toward the pooled drift of all trophies of the same
     rarity tier, because a single trophy's last two reads are mostly rounding
     noise: the page prints 0.63 for a rate that might really be 0.6349.
  3. Add a spread that grows with the square root of the horizon, from the
     observed scatter of the residual, never from a fixed constant. A short
     horizon keeps a tight band, which is where most of the score is won.

Every number written is rounded to four decimals, as the house's own rows are,
and the five quantiles of a row are kept non-decreasing.
"""

import json
import math
import os

LEVELS = (0.05, 0.25, 0.5, 0.75, 0.95)
# The standard normal's quantile at each level, fixed by the contest.
Z = (-1.6448536269514722, -0.6744897501960817, 0.0,
     0.6744897501960817, 1.6448536269514722)

LOW, HIGH = 0.01, 99.99     # the page's printed range, and the scorer's clamp
DAY_MINUTES = 1440.0

# The house baseline's spread, quoted in the rules: 0.5 logit per square-root
# day. A prize needs a strictly lower loss than it, so this is the number to
# beat, not a number to copy.
BASE_SIGMA = 0.5


def clamp(x):
    return LOW if x < LOW else (HIGH if x > HIGH else x)


def logit(pct):
    p = clamp(pct)
    return math.log(p / (100.0 - p))


def inv_logit(z):
    if z >= 40.0:
        return HIGH
    if z <= -40.0:
        return LOW
    return clamp(100.0 / (1.0 + math.exp(-z)))


def r4(x):
    """Four decimals, half up: the format the house's own rows are written in."""
    s = x * 10000.0
    w = math.floor(s)
    if s - w >= 0.5:
        w += 1
    v = w / 10000.0
    return float(v)


def series(case, i):
    """One trophy's recorded rates, oldest first, skipping reads that lack it."""
    out = []
    for read in case["history"]:
        rates = read.get("rates") or []
        if i < len(rates):
            v = rates[i]
            if isinstance(v, (int, float)) and math.isfinite(v):
                out.append(float(v))
    return out


def slots(case):
    return [r.get("slot") or r.get("at") for r in case["history"]]


def fit_drift(vals, times):
    """Least-squares slope of logit(rate) against time, in logit units per day.

    A rate that has not moved at all gives a slope of exactly zero, which is the
    honest reading of a page whose numbers have not changed: nothing in the
    history says it will move, so the median stays where it is.
    """
    n = len(vals)
    if n < 2:
        return 0.0
    xs, ys = [], []
    for v, t in zip(vals, times):
        xs.append(t)
        ys.append(logit(v))
    # Collapse identical timestamps to keep the normal equations well posed.
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx <= 1e-12:
        return 0.0
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    return sxy / sxx


def hours_between(a, b):
    """Hours from slot a to slot b, from ISO 8601 UTC stamps."""
    from datetime import datetime
    fmt = "%Y-%m-%dT%H:%M:%S"
    def parse(s):
        s = s.replace("Z", "")
        if "." in s:
            s = s.split(".")[0]
        return datetime.strptime(s, fmt)
    return (parse(b) - parse(a)).total_seconds() / 3600.0


def residual_scatter(case, ids, times_h, drifts):
    """The observed scatter of logit(rate) about each trophy's fitted line.

    This is the only honest source of a spread: it measures how far the page's
    printed rate actually wanders from the trend the fit believes in, which is
    exactly what the pinball loss charges for.
    """
    out = []
    for i in ids:
        vals = series(case, i)
        if len(vals) < 3:
            continue
        d = drifts[i]
        base = logit(vals[0])
        for v, t in zip(vals[1:], times_h[1:]):
            pred = base + d * t / 24.0
            out.append(logit(v) - pred)
    return out


def build_forecast(case):
    """One row per trophy: five quantiles of its rate at the case's target."""
    hist = case["history"]
    last = hist[-1]
    rates = last.get("rates") or []
    trophies = case["trophies"]
    ids = list(range(len(trophies)))

    slot_list = slots(case)
    # The horizon the band grows over. A case states it in minutes, but a case
    # that only names its target is read from the two stamps instead of being
    # given a horizon of zero, which would claim a certainty the history has
    # not earned and put the whole case's loss on rounding.
    horizon_days = float(case.get("horizon_minutes") or 0) / DAY_MINUTES
    if horizon_days <= 0:
        try:
            horizon_days = hours_between(slot_list[-1], case["target"]) / 24.0
        except Exception:
            horizon_days = 0.0
    if horizon_days <= 0:
        horizon_days = 1.0 / DAY_MINUTES

    # Time of each read in hours from the first one, for the per-trophy fits.
    times_h = [0.0]
    for k in range(1, len(slot_list)):
        try:
            times_h.append(times_h[-1] + hours_between(slot_list[k - 1], slot_list[k]))
        except Exception:
            times_h.append(float(k))

    drifts = {}
    for i in ids:
        vals = series(case, i)
        use = min(len(vals), len(times_h))
        drifts[i] = fit_drift(vals[-use:], times_h[-use:])

    # Shrink each drift toward the pooled drift of its tier, so one trophy's
    # rounding noise cannot masquerade as a trend. The weight grows with the
    # number of reads behind the fit.
    tiers = {}
    for i, t in enumerate(trophies):
        tiers.setdefault(t.get("tier") or "?", []).append(i)
    pooled = {}
    for tier, members in tiers.items():
        ds = [drifts[i] for i in members if drifts[i] != 0.0]
        pooled[tier] = sum(ds) / len(ds) if ds else 0.0

    resid = residual_scatter(case, ids, times_h, drifts)
    if resid:
        var = sum(r * r for r in resid) / len(resid)
        sigma_obs = math.sqrt(var)
    else:
        sigma_obs = 0.0

    # The band. A page that prints the same rates for hours has told us almost
    # nothing about how far they travel in a week, so the observed scatter is a
    # floor, not the answer: 35% of the house baseline's per-day width. That is
    # deliberately narrower than the baseline (which every prize must beat) and
    # far wider than the near-zero band a frozen history on its own would claim.
    per_day = sigma_obs / math.sqrt(max(horizon_days, 1.0 / 24.0))
    sigma = max(per_day * math.sqrt(horizon_days),
                0.35 * BASE_SIGMA * math.sqrt(horizon_days))

    rows = []
    for i in ids:
        r = rates[i] if i < len(rates) else None
        if not isinstance(r, (int, float)) or not math.isfinite(r):
            # No rate in the answering read to fall back on: use the last one
            # this trophy was seen at, the scorer's own invalid-case behaviour.
            seen = series(case, i)
            r = seen[-1] if seen else LOW
        r = float(r)

        d = drifts[i]
        n_reads = len(series(case, i))
        w = n_reads / (n_reads + 4.0)      # shrink harder when reads are few
        d_shrunk = w * d + (1.0 - w) * pooled.get(trophies[i].get("tier") or "?", 0.0)

        centre = logit(r) + d_shrunk * horizon_days
        q = [r4(inv_logit(centre + z * sigma)) for z in Z]
        # Keep the row non-decreasing after rounding, as the format requires.
        for k in range(1, 5):
            if q[k] < q[k - 1]:
                q[k] = q[k - 1]
        rows.append({"id": trophies[i]["id"], "q": q})
    return {"trophies": rows}


def main():
    in_dir = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    for name in sorted(os.listdir(in_dir)):
        if not name.endswith(".in"):
            continue
        with open(os.path.join(in_dir, name), "r", encoding="utf-8") as fh:
            case = json.load(fh)
        doc = build_forecast(case)
        stem = name[:-3]
        with open(os.path.join(out_dir, stem + ".out"), "w", encoding="utf-8") as fh:
            json.dump(doc, fh, separators=(",", ":"), sort_keys=False)


if __name__ == "__main__":
    main()
