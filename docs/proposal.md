# Proposal: Synthetic Surface Generation from ISO 25178-2 Parameters

Nov 4, 2026 · @Josh

## Introduction

This project asks how much of a measured surface is encoded in its ISO 25178-2 areal texture parameters, by testing whether a model given only those parameters can regenerate the surface. Parameters are handed to the model one family at a time (height, spatial, hybrid, functional/volume, feature), each reconstruction is re-measured with the same pipeline, and the error at each step shows which families constrain the surface and which features never return.

Three kinds of generator are tested on the same task: general-purpose foundation models (Claude, GPT, Gemini, and an open-weight model), classical spectral synthesis as the method a metrologist would use by hand, and a purpose-trained conditional diffusion model as the ceiling on what the parameters can support. Comparing the three separates two explanations for any failure: the parameter set does not carry the information, or the model cannot use it.

The immediate deliverable is a course memo and benchmark for the surface metrology class. The intended follow-on is a paper with the class instructor, and the trained generator is the planned starting point for thesis work on defect synthesis in ceramic additive manufacturing.

## Motivation

ISO 25178-2 field parameters are summaries, and summaries discard position. Sa, Sq, Sal and Str describe a surface as a stationary random process; two surfaces with identical values can differ by a single deep scratch or fifty spatter particles. The feature parameters (Spd, Spc, Sda, Sha) come closest to naming discrete features, but they count and average them without recording where they are or what shape they take. For additively manufactured and machined parts, the features the parameters miss are often the ones that decide whether the part is accepted.

Reconstruction is a direct test of that gap. If a surface can be regenerated from its parameters to within measurement spread, the parameters carry the information; if every parameter is matched but the scratch is gone, the standard does not constrain that feature. Doing this family by family maps which parameters add information and which are implied by the ones before them.

Foundation models are the right first probe for three reasons. They are the only generators that have read the standard, so they test whether understanding the definitions is enough to apply them. They are what a practitioner would actually reach for when asked to produce a surface with a given specification. And their failure modes are informative: a language model emits a height map one value at a time with no spatial memory, so where it fails exposes how much of a surface is structure rather than statistics.

A second motivation is practical. Measured surface datasets are expensive and small; the catalog for this project is twelve scans. A generator that produces surfaces faithful to measured parameters, and later to planted defects, would give computer-vision work on surface inspection the training data it currently lacks.

## Task definition

Given a reference height map z(x, y) on an N × N grid with sampling interval Δx, and the vector of ISO 25178-2 parameters P(z) computed on it after a fixed levelling and S-filter pipeline, a generator G must produce a height map ẑ on the same grid such that P(ẑ) ≈ P(z). The generator receives only the grid specification, the filter settings, and a subset of P(z); it never sees z.

**Progressive families.** The subset grows in five levels, each level containing all families before it:

1. Height: Sa, Sq, Ssk, Sku, Sp, Sv, Sz
2. - Spatial: Sal, Str, Std
3. - Hybrid: Sdq, Sdr
4. - Functional and volume: Sk, Spk, Svk, Smr1, Smr2, Vmp, Vmc, Vvc, Vvv
5. - Feature: Spd, Spc, S10z, Sda, Sha, Sdv, Shv

Each level is an independent, stateless request with the same system prompt; nothing from earlier levels or runs is passed back.

**Two spatial conditions per scan.** A text model can return at most a 128 × 128 grid in one response (about 45k output tokens; the largest common output limit is 128k and Gemini's is 64k), so each 1000 × 1000 scan yields two reference surfaces:

- Coarse: the full field block-averaged to 128 × 128, Δx about 8× the instrument pitch. Keeps lay, waviness and long features.
- Native: a 128 × 128 crop at the instrument pitch from a fixed, recorded location. Keeps fine roughness and small features.

**Output contract.** The model returns a SCALE line giving the physical heights of integers 0 and 1000, then 128 rows of 128 comma-separated integers. The harness rescales to micrometres, attaches the prompt's Δx, and the result enters the same measurement pipeline as the reference.

**Secondary conditions.** Code generation (the model writes a function that returns the array; no grid-size limit, tests knowledge of synthesis methods rather than direct generation) and feedback refinement (the model sees its previous surface's measured parameters and revises). Both are reported separately from the primary stateless condition.

**Success criterion.** A parameter is recovered when its mean relative error over K runs is within 10% and within two standard deviations of the spread between re-measured patches of the same reference surface.

## Data

The primary data are twelve coherence scanning interferometry (CSI) scans supplied by the class instructor, covering six surface categories. Each is provided raw and with form removed (best-fit plane, cylinder, or 4th-order polynomial as recorded); the form-removed versions are the reference surfaces. The S-filter nesting index is set by this project and applied identically to every reference and generated surface.

| Category | Surfaces | Process and material | Objective | Field | Δx (µm) | Grid |
| --- | --- | --- | --- | --- | --- | --- |
| Periodic | 3 | Turning, vertical milling (electroformed Ni); LPBF Inconel 625 | 5.5×, 10× | 1.56–1.66 mm | 1.56–1.62 | 1000–1024 |
| Directional, anisotropic | 4 | Ground ×3 (one with deep groove); cold rolled with pits; 316 SS | 2.75× | 3.05 mm | 3.05 | 1000–1024 |
| Bi-directional | 1 | Lapped (electroformed Ni) | 5.5× | 1.56 mm | 1.56 | 1000 |
| Isotropic | 2 | Polished 316 SS; SLA-printed alumina | 1.5×, 20× | 0.95 mm, 420 µm | 1.48, 0.42 | 640×480, 1000 |
| Isotropic, weak directionality | 1 | Powder coated | 2.75× | 3.05 mm | 3.05 | 1000 |
| Engineered | 1 (+1 to add) | DLP photocurable polymer | 20× | 420 µm | 0.42 | 1000 |

The experimental unit is the surface category, not a dataset of many scans. Replication comes from K repeated generations per prompt and from multiple native-resolution patches per scan (a 1000 × 1000 scan holds 49 non-overlapping 128 × 128 patches).

A secondary synthetic reference set complements the measured data. Surfaces are built by spectral synthesis to target Sq, Ssk, Sku, Sal and Str, then scratches, pits and spatter are planted from a recorded feature list. These give a ground-truth feature inventory that measured scans cannot, so feature survival can be scored exactly. The synthetic set follows the virtual-instrument specification in the October memo: 512 × 512, 1.0 µm pitch, S-filter 2.5 µm, L-filter 0.25 mm, parameters validated against ISO 25178-71 softgauges.

## Models and baselines

| Generator | Role | Access | Notes |
| --- | --- | --- | --- |
| Claude (Opus 5.5 or Sonnet 5.5; Fable 5.1 if budget allows) | Primary closed model | Anthropic API, batch pricing | 128k output; adaptive thinking always on, effort level fixed and logged |
| GPT-6 (Astra or Sol) | Second closed model, if budgeted | OpenAI API; student ChatGPT for prompt prototyping only | 128k output |
| Gemini 3.1 Pro | Third closed model | AI Studio free tier or paid API | 64k output; sets the 128 × 128 ceiling |
| Open-weight model (GLM-5.3-Flash, Qwen3.8-27B, or gpt-oss-120b, by HPC allocation) | Controlled open model; resolution sweep | Lab HPC via vLLM | Pinned weights; unlimited runs; two sizes from one family if possible |
| Classical spectral synthesis | Method baseline | NumPy, in-house | Johnson translator + ACF shaping; matches Sq, Ssk, Sku, Sal by construction |
| Conditional diffusion model | Specialized ceiling | Trained on lab HPC | Small U-Net on 128 px patches, parameters injected by FiLM, family-level conditioning dropout so it runs the same progressive protocol |

The closed models are run only through their APIs with pinned model strings, fixed temperature and effort, and logged token usage. Chat interfaces are used for prompt development and never for reported results, because they do not expose model versions and may execute code invisibly.

The diffusion model is the piece that turns the benchmark into a study of the task. If it recovers a family the language models miss, the information was there and the language models could not use it. If both miss it, the parameters do not carry it.

## Evaluation protocol

Every generation, from any model at any level, is scored the same way:

1. Parse validity: 128 rows of 128 integers in range, SCALE line present. Malformed outputs are logged by failure type and excluded from error statistics rather than scored as zero.
2. Rescale to micrometres, attach the prompt's Δx, level and S-filter with the reference pipeline, recompute the full parameter vector with the same in-house implementation.
3. Relative error |P(ẑ) − P(z)| / |P(z)| per parameter, aggregated by family, reported separately for families provided at that level and families withheld. Withheld-family error measures what the given families imply about the rest.
4. Structural comparison: radially averaged PSD and areal autocorrelation distance to the reference; ISO 25178-2 watershed segmentation with Wolf pruning at a fixed threshold, comparing counts, areas and aspect ratios of significant hills and dales; a line detector for scratches. On the synthetic set, feature survival is scored against the planted feature list.
5. K independent generations per prompt (K = 3–5); mean and standard deviation across runs. Per-request logging of model string, temperature, effort, and input/output token counts.

The primary result is error versus family level: one curve per generator, per surface category, with the classical and diffusion baselines on the same axes, split into provided-family and withheld-family panels. The key case for the gap analysis is a reconstruction that recovers every parameter in the feature family and still has no scratch.

## Deliverables, timeline, budget

**Deliverables**

- Two-page class memo: motivation, measurement details, analysis approach, ISO references.
- Benchmark harness (manifest builder, prompt builder, model clients, runner, parser, evaluator) with the ISO 25178-2 parameter implementation validated against softgauges.
- Results tables and family-level error curves per category and model.
- Trained conditional diffusion model and its curves on the same protocol.
- Draft paper with the class instructor if results warrant.

**Order of work**

1. Parameter implementation and softgauge validation; manifest from the twelve scans (coarse and native references).
2. Classical synthesis baseline; prompt development on subscription chat interfaces until outputs parse reliably.
3. Pilot of \~10 API runs per candidate model to measure parse rate, token usage with thinking, and Sonnet-versus-Opus difference; fix design and budget.
4. Full stateless run through batch APIs; open-model run and resolution sweep on HPC.
5. Diffusion model training and evaluation on the same protocol.
6. Secondary conditions (code generation, feedback refinement) as budget allows.
7. Analysis, memo, paper draft.

**Budget (batch pricing, 128 × 128, \~47k output tokens per run)**

| Design | Runs per model | Sonnet 5.5 | Opus 5.5 | Fable 5.1 / GPT-6 Astra | Gemini 3.1 Pro |
| --- | --- | --- | --- | --- | --- |
| K = 3, one native patch | 360 | $85 | $170 | $425 | $105 |
| K = 5, one native patch | 600 | $140 | $280 | $710 | $170 |
| K = 5, three native patches | 1,200 | $280 | $565 | $1,415 | $340 |

Add 20–50% for thinking tokens, to be measured in the pilot. The open model, classical baseline and diffusion model cost HPC time only. Recommended starting point: one Claude model at K = 5 plus the open model, about $150–300, with a second closed model added if the department funds it.

**Open questions**

- [ ] S-filter nesting index: project choice or lab convention?
- [ ] Confirm the "Rupert" samples are Rubert comparison specimens for citation.
- [ ] HPC allocation: which GPUs, and therefore which open model.
- [ ] SCALE line chosen by the model, or fixed from Sp and Sv?
