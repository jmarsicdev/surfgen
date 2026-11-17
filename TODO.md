# To check

Open items from the 2026-11-12 pilot. Background and numbers are in `results/README.md`.

## Design changes on 2026-11-17

The benchmark is now one conversation per surface in two stages (height + functional/volume, then
spatial + hybrid + feature), with no sampling interval or levelling information in the prompt.
Initial tests are on Sample_23 (original name Sample_8_13_2.75x). Items below that mention five
levels or the prompt's grid sentence predate this.

- [ ] **Stage 2 wording is mine:** "Additional parameters (ISO 25178-2): … Generate the height map
      again so that all parameters given so far are matched." Replace with the wording from the
      running doc if it differs.
- [ ] **The system prompt still says "along with the measurement grid"**, which is no longer given.
- [ ] **No pitch in the prompt.** Every stage 2 parameter except Str and Std depends on the
      sampling interval, so the model has to guess it; scoring uses the true one. Compare the
      with-pitch and without-pitch chains on Sample_21 before settling this.
- [ ] **Slope targets are out of reach at 200 × 200.** For Sample_21, pure pixel-scale noise at the
      target Sq gives Sdq = 0.0185 against a target of 0.0543.
- [ ] Sample names: the catalog's original name "Sample_8_13_2.75x" is raw file Sample_10 and
      form-removed file Sample_23. Raw file "Sample_8" is a different scan (Ground_10_top6,
      form-removed Sample_21), which all results before 2026-11-17 used.
- [ ] The professor's ChatGPT test produced 1000 × 1000 by writing and running code. Decide whether
      code generation becomes a condition here.

## Decision: how to handle the resolution mismatch

Targets come from the full-resolution scan, and the model outputs a coarser grid over the same
field. On that grid the real surface itself matches only 3–4 of 28 targets (Sa and Sq 30–41% low,
slopes 84–99% low), so part of every model's error comes from the grid.

- [ ] **Option A: keep the design, always report the resampled-real row.** Every results table
      carries a row scoring the measured surface resampled to the output grid, so readers can see
      which misses are the grid's. No change to the plan. Needs the reference row built into the
      runner (currently computed by a one-off script).
- [ ] **Option B: add a second target set computed on the resampled scan.** Report both. Separates
      what the model can do from what the grid allows. It means downsampling before computing
      metrics for that second set, which was ruled out for the primary targets.
- [ ] Ask the instructor which they would accept in the memo.

## Parameter code: not validated

Nothing in `src/surfgen/params.py` has been checked against a reference. The targets in every
prompt come from this code.

- [ ] Compare all 28 parameters against Zygo Mx or MountainsMap for two or three scans (one
      anisotropic, one isotropic, one with strong features). Export the ISO 25178 table and line it up.
- [ ] Run the ISO 25178-71 softgauges through `params.compute` (proposal, order of work step 1).
- [ ] **Height (Sa, Sq, Ssk, Sku, Sp, Sv, Sz):** direct formulas; expected to agree.
- [ ] **Spatial (Sal, Str):** autocorrelation by zero-padded FFT, 0.2 threshold found along 180
      radial directions with linear interpolation. Commercial software may differ by a few percent.
- [ ] **Std:** defined here as the direction of slowest autocorrelation decay, measured from the
      row (x) direction. Check the convention and reference axis against Mx. It is noise for
      isotropic surfaces.
- [ ] **Hybrid (Sdq, Sdr):** central-difference gradients; the standard's Sdr uses a triangulated
      area. Check agreement on a rough surface.
- [ ] **Functional (Sk, Spk, Svk, Smr1, Smr2):** 40% minimum-slope secant on the material ratio
      curve. Check against ISO 13565-2 style output.
- [ ] **Volume (Vmp, Vmc, Vvc, Vvv):** material ratios fixed at 10% and 80%.
- [ ] **Feature (Spd, Spc, S10z, Sda, Sha, Sdv, Shv): weakest.** Simplified segmentation:
      h-maxima pruning at 5% of Sz in place of full Wolf pruning, motifs touching the edge are
      kept, hill and dale volumes use an approximate saddle height. Expect real disagreement;
      treat current values as provisional.

## Data and filtering

- [ ] Confirm with the instructor that the scans are form-removed only. Found by subtracting each
      processed scan from its raw pair: the difference is exactly the catalogued plane, cylinder or
      4th-order polynomial, with no S- or L-filter. The catalog's S-filter column is blank.
- [ ] Decide whether an S-filter should be applied anyway (the proposal lists the nesting index as
      an open question). Without one, Sdq and Sdr include instrument noise at the pixel scale.
- [ ] **Sample_26 is identical to Sample_13.** The catalog lists "Sample_13" as both the raw and
      the plane-removed name. Get the missing export or drop one.
- [ ] **Sample_24's raw pair (Sample_11) is a `.dat` file** and was not compared.
- [ ] **Sample_24 is 640 × 480.** The square output grid currently spans the shorter side only, so
      it covers part of the field. Decide how to treat it.
- [ ] 1024 × 1024 scans give a non-integer pitch ratio at 200 × 200 (5.12×). Harmless for
      generation; matters if a resampled reference is built.
- [ ] Missing points (up to 0.5% of a scan) are filled with the nearest valid height before
      parameters are computed. Check this against how Mx treats them.

## Prompt

- [ ] Output rows are labelled `R001:` …; this differs from the outline and fixed the short
      outputs (8 of 8 valid against 0 of 2).
- [ ] The sentence "Your surface will be levelled with a least-squares plane before it is measured"
      was added and approved on 2026-11-12.
- [ ] The one-line parameter definitions are my wording. Read them once for accuracy, especially
      Std (reference axis) and Spd (5% of Sz pruning).
- [ ] Values are given to four significant figures.

## Before the real runs

- [ ] Parse rate: two formats tested once each per size is not a rate. The proposal's pilot of
      about 10 runs per model would establish it.
- [ ] Results so far are one surface, one level, one generation per cell. No model or effort
      comparison can be drawn from them.
- [ ] Reported runs must go through the API with pinned model strings. The pilot used the Claude
      Code CLI on a subscription. No API or batch client exists yet.
- [ ] Temperature cannot be set on Opus 5.5 or Fable 5.2; the proposal's "fixed temperature"
      applies only to models that accept it. Effort is the logged control.
- [ ] Model choice: the proposal names Fable 5.1; the pilot used Fable 5.2 (current, cheaper).
- [ ] Gemini 3.1 Pro's 64k output limit (per the proposal) is below the roughly 82k tokens a
      200 × 200 grid needs. It could run 128 × 128 only.
- [ ] Not built: K-repeat runner, levels 1–4 sweep, other providers, classical baseline, diffusion
      baseline, watershed/scratch feature-survival scoring.
- [ ] Confirm the "Rupert" samples are Rubert comparison specimens (proposal open question).
