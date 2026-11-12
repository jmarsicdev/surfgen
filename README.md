# surfgen

Benchmark: can a model regenerate a measured surface from its ISO 25178-2 areal parameters alone?
The design is in `docs/proposal.md` and `docs/outline.pdf`.

## Layout

| Path | Contents |
| --- | --- |
| `data/catalog/references.csv` | The 13 form-removed reference scans (Samples 14–26) and their raw pairs |
| `data/raw/` | The `.datx` scans. Not in git; unzip "Renamed files" here |
| `src/surfgen/io.py` | `.datx` loader; coarse and native 128 × 128 references |
| `src/surfgen/params.py` | Levelling, S-filter, the 28 parameters in five families |
| `src/surfgen/protocol.py` | System and user prompt, output parser, scoring |
| `src/surfgen/pilot.py` | One generation end to end, with a budget projection |
| `runs/` | One folder per run: prompt, response, arrays, `record.json`, figure. Not in git |

## Setup

```sh
uv venv .venv
uv pip install --python .venv/bin/python -e .
```

## One pilot run

```sh
.venv/bin/python -I -m surfgen.pilot --sample Sample_21 --condition coarse --level 5 \
    --model claude-opus-5-5 --effort medium
```

`--dry-run` prints the prompt without calling a model. The pilot client is the Claude Code CLI in
print mode, which bills the claude.ai subscription instead of the API. It sends only the benchmark's
system and user prompt, with no tools, so the token counts carry over to API pricing. Reported
results must come from the API with a pinned model string.

## Not done yet

- Parameters are not validated against the ISO 25178-71 softgauges. The feature family uses a
  simplified segmentation (h-maxima pruning at 5 % of Sz, edge motifs kept, saddle height
  approximated), so treat Spd, Spc, S10z, Sda, Sha, Sdv, Shv as provisional.
- The S-filter nesting index is set to 3 × the pitch (`S_FILTER_PIXELS`), pending the open question
  in the proposal.
- Only the central native patch is cut; the design allows up to 49 per scan.
- No API or batch client, no other models, no baselines, no K-repeat runner.
