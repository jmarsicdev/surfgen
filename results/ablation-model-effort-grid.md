# Ablation: model, effort and grid size

Run on 2026-11-12. Full tables, figures and the per-parameter errors are in [`README.md`](README.md);
this file isolates the three-factor comparison and what it can and cannot say.

## What was varied

Three factors, two settings each, every combination run once: 2 × 2 × 2 = 8 generations.

| Factor | Settings |
| --- | --- |
| Model | Claude Opus 5.5, Claude Fable 5.2 |
| Effort | medium, high |
| Output grid | 128 × 128, 200 × 200 |

## What was held fixed

| Item | Value |
| --- | --- |
| Surface | Sample_21, ground 316 SS, 1000 × 1000 at 3.06 µm |
| Targets | 28 ISO 25178-2 parameters from the whole scan, no S- or L-filter |
| Level | 5 (all five families in the prompt) |
| Prompt | Identical apart from the grid size and pitch |
| Output | Whole field of view, labelled rows |
| Repeats | 1 per cell |

**Read every comparison below with the last row in mind.** With one generation per cell there is no
estimate of run-to-run spread, so a difference between two cells cannot be told apart from noise.
The tables show what happened, and the "pattern" lines say whether a factor moved the result the
same way in all four of its paired comparisons. That is the most this design supports.

## Summary of each cell

"Within 10%" counts the parameters, out of 28, whose relative error is 0.10 or less.

| Grid | Model | Effort | Within 10% | Kurtosis error | Hill-area (Sha) error | PSD difference | Thinking tokens | Batch cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 128 | Opus 5.5 | medium | 7 | 12.6 | 37.5 | 0.60 | 1,167 | $0.35 |
| 128 | Opus 5.5 | high | 10 | 3.39 | 16.1 | 0.59 | 2,289 | $0.36 |
| 128 | Fable 5.2 | medium | 6 | 1.70 | 10.9 | 0.79 | 2,425 | $0.72 |
| 128 | Fable 5.2 | high | 8 | 0.29 | 9.27 | 0.75 | 3,035 | $0.73 |
| 200 | Opus 5.5 | medium | 7 | 0.85 | 7.11 | 1.26 | 1,069 | $0.82 |
| 200 | Opus 5.5 | high | 5 | 9.47 | 50.3 | 0.58 | 2,170 | $0.83 |
| 200 | Fable 5.2 | medium | 5 | 2.65 | 16.1 | 0.89 | 1,023 | $1.64 |
| 200 | Fable 5.2 | high | 8 | 0.26 | 8.62 | 0.68 | 6,859 | $1.76 |

Kurtosis and hill area are shown because they are the parameters that varied most between runs;
most others were either matched by every run (Sp, Sv, Sz, Std) or missed by every run (Sdq, Sdr,
Spd, Spc).

## Effect of effort (medium → high)

| Model | Grid | Within 10% | Kurtosis error | Sha error | PSD difference |
| --- | --- | --- | --- | --- | --- |
| Opus 5.5 | 128 | 7 → 10 | 12.6 → 3.39 | 37.5 → 16.1 | 0.60 → 0.59 |
| Opus 5.5 | 200 | 7 → 5 | 0.85 → 9.47 | 7.11 → 50.3 | 1.26 → 0.58 |
| Fable 5.2 | 128 | 6 → 8 | 1.70 → 0.29 | 10.9 → 9.27 | 0.79 → 0.75 |
| Fable 5.2 | 200 | 5 → 8 | 2.65 → 0.26 | 16.1 → 8.62 | 0.89 → 0.68 |

- **Pattern for Fable:** high effort was better on all four measures at both grid sizes.
- **Pattern for Opus:** mixed. Better at 128, worse at 200 on everything except the PSD.
- **Cost of high effort:** 1–7% more per run.
- Mean parameters within 10%: 6.25 at medium, 7.75 at high.

## Effect of model (Opus 5.5 → Fable 5.2)

| Grid | Effort | Within 10% | Kurtosis error | Sha error | PSD difference |
| --- | --- | --- | --- | --- | --- |
| 128 | medium | 7 → 6 | 12.6 → 1.70 | 37.5 → 10.9 | 0.60 → 0.79 |
| 128 | high | 10 → 8 | 3.39 → 0.29 | 16.1 → 9.27 | 0.59 → 0.75 |
| 200 | medium | 7 → 5 | 0.85 → 2.65 | 7.11 → 16.1 | 1.26 → 0.89 |
| 200 | high | 5 → 8 | 9.47 → 0.26 | 50.3 → 8.62 | 0.58 → 0.68 |

- **Pattern:** none that holds across all four. Opus had more parameters within 10% in three of
  four pairs; Fable had lower kurtosis and hill-area error in three of four.
- **Fable's errors varied less.** Its hill-area error stayed between 8.6 and 16.1 across its four
  runs; Opus's ranged from 7.1 to 50.3.
- **Cost:** Fable is twice the price per run.
- Mean parameters within 10%: 7.25 for Opus, 6.75 for Fable.

## Effect of grid (128 → 200)

| Model | Effort | Within 10% | Kurtosis error | Sha error | PSD difference |
| --- | --- | --- | --- | --- | --- |
| Opus 5.5 | medium | 7 → 7 | 12.6 → 0.85 | 37.5 → 7.11 | 0.60 → 1.26 |
| Opus 5.5 | high | 10 → 5 | 3.39 → 9.47 | 16.1 → 50.3 | 0.59 → 0.58 |
| Fable 5.2 | medium | 6 → 5 | 1.70 → 2.65 | 10.9 → 16.1 | 0.79 → 0.89 |
| Fable 5.2 | high | 8 → 8 | 0.29 → 0.26 | 9.27 → 8.62 | 0.75 → 0.68 |

- **Pattern:** none. The larger grid did not give a consistently better match on any measure.
- **What the grid does change is the ceiling.** The measured surface resampled to 200 × 200 is
  closer to the full-scan targets than at 128 × 128 (median height error 0.30 against 0.55,
  spatial 0.57 against 0.85), so there is more room to be right. These runs did not use it.
- **Cost:** 2.3–2.4× more per run.
- Mean parameters within 10%: 7.75 at 128, 6.25 at 200.

## What did not change with any factor

- **Surface type.** All eight are straight vertical stripes with a few deep grooves and isolated
  spikes (see `figures/overview.png`).
- **Extremes.** Sp, Sv and Sz within 2% in seven of eight runs.
- **Lay direction.** 90° against a target of 89° in every run.
- **Slopes.** Sdq and Sdr 72–98% low in every run, the same as the resampled measured surface.
- **Peak density and curvature.** Spd and Spc 88–98% low in every run.
- **Anisotropy.** Str 54–82% low in every run: the stripes are straighter than real grinding marks.

## Tentative reading

- The clearest signal is **Fable at high effort**: it had the lowest kurtosis and hill-area errors
  at both grid sizes and was the only configuration to improve on all four measures with effort.
  It also thought the most (3,035 and 6,859 thinking tokens).
- Opus's results swing widely between cells, which looks more like run-to-run variation than an
  effect of effort or grid.
- No factor changed what kind of surface was produced. The differences are in how well the planted
  grooves and spikes were tuned to the distribution-shape and feature targets.
- On cost alone, grid size matters most (2.3×), then model (2×), then effort (under 7%).

## To turn this into a real ablation

- [ ] **Repeats.** K = 5 per cell, to get a spread. This is the one change that makes the
      comparisons meaningful. Cost at batch prices for this one surface and level: about $9 for
      the four Opus cells plus $19 for the four Fable cells, with the existing runs counted as one
      repeat each (32 more runs, about $29 in total).
- [ ] **A second surface with different character**, such as the isotropic SLA alumina (Sample_15)
      or the LPBF surface (Sample_25), to see whether "stripes plus spikes" is specific to ground
      surfaces.
- [ ] **Levels 1–4.** Level 5 gives the model everything. Whether effort or model matters more
      when fewer families are given is untested.
- [ ] **Low and xhigh effort**, to see whether the Fable trend continues in both directions.
- [ ] **Sonnet 5.5**, the cheapest option in the proposal, at half Opus's price.
- [ ] **Resampled-scan targets** alongside the full-scan ones (Option B in `TODO.md`), so the grid
      comparison is not confounded by how reachable the targets are at each size.
- [ ] Report run-to-run spread for every measure before comparing any two cells.
