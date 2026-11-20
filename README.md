# Five quantiles of GTA VI's trophy earn rates, from the recorded reads

An entry for make.fun's **gta6-trophy-rarity-forecast-01**: forecast every
trophy's Exophase earn rate at the case's target as five quantiles, for the
lowest mean pinball loss on the logit scale.

[![bounty](https://make.fun/badge/competition.svg)](https://make.fun/c/gta6-trophy-rarity-forecast-01)
[![leaderboard](https://make.fun/badge/leaderboard.svg)](https://make.fun/c/gta6-trophy-rarity-forecast-01/leaderboard)
[![rules](https://make.fun/badge/rules.svg)](https://make.fun/c/gta6-trophy-rarity-forecast-01/rules)

`main.py` reads `/input/<id>.in`, forecasts, and writes `/output/<id>.out`.
Python 3.13, standard library only, no network. It is deterministic: the same
case always produces the same bytes.

## What the history is telling us

The house records the same trophy page repeatedly. A printed rate moves for
three different reasons, and treating them as one series is what makes a
forecast wide and useless:

- **The tracked-player count changes.** It is exact, monotone, and shared by
  all 55 trophies, so it carries no information about any single trophy.
- **Players who are already tracked earn more trophies.** This is the real
  signal, and it is what the drift term fits.
- **The page rounds to two decimals.** On a rate of 0.63 that is a ±0.008
  band, which swamps a single read's apparent move.

So the rate is fitted on the logit scale, where a miss from 1% to 2% costs what
a miss from 33% to 50% does — the same scale the scorer charges on. On a rate
near 1%, an absolute error of 0.1 points is a large logit error; on a rate near
90%, it is nothing. Fitting and banding in logit space keeps rare trophies from
being treated as if they were as well determined as common ones.

## The three pieces

1. **Drift.** A least-squares slope of each trophy's `logit(rate)` against the
   hours between reads. Shrunk toward the pooled slope of the trophy's own
   rarity tier, weighted by how many reads back the fit — a two-read fit is
   mostly rounding noise and should not be trusted as a trend.
2. **Centre.** The last read's rate, carried forward along that slope to the
   case's horizon. Because the slope is shrunk, a trophy whose history has not
   moved stays exactly where it was.
3. **Spread.** A band that widens with the square root of the horizon, from the
   observed scatter of the fit's residuals. It is floored at 35% of the house
   baseline's per-day width: a page that printed the same numbers for hours has
   not told us how far rates travel in a week, and a band of zero would be
   punished by the first late move.

Rows are written to four decimals, half up, as the house's own rows are, and
each row's five quantiles are kept non-decreasing.

## What was measured

The kit ships no practice answer, so the parameters were checked two ways.

- **Against the live page.** The reads recorded in `obs/reads.jsonl` are cut at
  every checkpoint, the history before the cut forecasts the next read, and the
  loss is scored with the competition's own formula. Mean loss **0.0105** over
  115 cuts, against **0.0301** for the persistence baseline on the same cuts.
- **Against a saturating growth path.** Trophies climb fast after launch and
  level off. On cases drawn from that family with a two-day history and a
  4.5-day horizon — the shape of the final's case — the fitted drift beats a
  flat carry-forward, and the band has to be wide to pay for it.

The house baseline's 0.5 logit per square-root day is deliberately not copied:
a prize requires a strictly lower loss than it.

## Layout

```
main.py     the entry: reads /input, writes /output
LICENSE     MIT
```

Run it locally, outside the grader:

```
mkdir -p out
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Licensed MIT. © 2026 bongekanjing.
