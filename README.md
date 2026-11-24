# surfgen

Benchmark: can a model regenerate a measured surface from its ISO 25178-2 areal parameters alone?
The design is in `docs/proposal.md` and `docs/outline.pdf`.

Results: the code-generation baseline is in [`results/codegen-opus-5-5/`](results/codegen-opus-5-5/README.md);
the earlier text-grid pilots are in [`results/README.md`](results/README.md).

## Current design (2026-11-24): code generation

Each model writes one program, once, that generates a height map from ISO 25178-2 parameters. Every
surface is then run through that program unchanged. The program produces a stage 1 surface (height
and functional/volume parameters) and a stage 2 surface built on it (all parameters), at the scan's
own size and sampling interval. The prompt gives parameter definitions and one example surface's
values and no direction on method. Model-written code runs in a bubblewrap sandbox.

```sh
.venv/bin/python -I -m surfgen.codegen write --model claude-opus-5-5       # model writes and tests its program
.venv/bin/python -I -m surfgen.codegen apply runs/<run> --samples Sample_23 Sample_21 --repeats 3
```

The sections below describe the earlier text-grid design (`surfgen.pilot`), kept for reference.

## Layout

| Path | Contents |
| --- | --- |
| `data/catalog/references.csv` | The 13 form-removed reference scans (Samples 14–26) and their raw pairs |
| `data/raw/` | The `.datx` scans. Not in git; unzip "Renamed files" here |
| `src/surfgen/io.py` | `.datx` loader; whole-scan reference and output pitch |
| `src/surfgen/params.py` | Levelling, S-filter, the 28 parameters in five families |
| `src/surfgen/protocol.py` | System and user prompt, output parser, scoring |
| `src/surfgen/codegen.py` | Code-generation condition: model writes a program, we run and score it |
| `src/surfgen/pilot.py` | Earlier text-grid design: one two-stage conversation end to end |
| `runs/` | One folder per run: prompt, response, arrays, `record.json`, figure. Not in git |

## Setup

```sh
uv venv .venv
uv pip install --python .venv/bin/python -e .
```

## Design as of 2026-11-17

One conversation per surface, in two stages:

1. Height (Sa, Sq, Ssk, Sku, Sp, Sv, Sz) and functional/volume (Sk, Spk, Svk, Smr1, Smr2, Vmp, Vmc,
   Vvc, Vvv). The model returns a height map.
2. In the same conversation, spatial (Sal, Str, Std), hybrid (Sdq, Sdr) and feature (Spd, Spc, S10z,
   Sda, Sha, Sdv, Shv) are added. The model returns a second height map.

Target parameters are measured on the whole form-removed scan at the instrument pitch, with no
cropping or resampling. The model returns a 200 × 200 grid (`--grid`) of labelled rows. Stage 1
opens with one line giving the scan's size and sampling interval and saying the output covers the
same area; no levelling is stated. `--grid-info output` gives the output grid's sampling interval
instead, and `--grid-info none` gives nothing. Scoring always uses the sampling interval at which the
grid spans the scan's field of view (about 5× the scan's), after a least-squares plane is removed.

The generated grid cannot hit every whole-scan target, because several parameters depend on pitch.
Score results against what the measured surface reaches when resampled to the same grid.

This replaces the proposal's five independent levels and its 128 × 128 coarse and native conditions.
The earlier single-request results in `results/` used five families in one prompt.

## One pilot chain

```sh
.venv/bin/python -I -m surfgen.pilot --sample Sample_23 --grid 200 \
    --model claude-opus-5-5 --effort medium
```

`--dry-run` prints the prompts without calling a model. The pilot client is the Claude Code CLI in
print mode, which bills the claude.ai subscription instead of the API. It sends only the benchmark's
system and user prompt, with no tools, so the token counts carry over to API pricing. Reported
results must come from the API with a pinned model string.

## Not done yet

- Parameters are not validated against the ISO 25178-71 softgauges. The feature family uses a
  simplified segmentation (h-maxima pruning at 5 % of Sz, edge motifs kept, saddle height
  approximated), so treat Spd, Spc, S10z, Sda, Sha, Sdv, Shv as provisional.
- No S- or L-filter is applied (`S_FILTER_PIXELS = 0`). The supplied scans are form-removed only:
  subtracting each from its raw pair leaves exactly the catalogued plane, cylinder or 4th-order
  polynomial. Sample_24's pair (Sample_11, `.dat`) was not checked, and Sample_26 is identical to
  Sample_13.
- No per-surface error floor in the runner yet.
- No API or batch client, no other models, no baselines, no K-repeat runner.
