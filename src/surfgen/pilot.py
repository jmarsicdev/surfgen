"""One two-stage conversation for one surface, scored, with a budget projection.

    python -I -m surfgen.pilot --sample Sample_23 --grid 200

Stage 1 gives the height and functional/volume families; stage 2 adds spatial, hybrid and
feature in the same conversation. Targets are measured on the whole scan. Stage 1 opens by
giving the scan's size and sampling interval and saying the output covers the same area
(--grid-info changes this). No levelling is stated. Scoring always uses the sampling
interval at which the grid spans the scan's field of view.

Client: the Claude Code CLI in print mode, billed to the claude.ai subscription rather
than the API. It sends only the benchmark prompts with no tools, so token counts transfer
to the API; reported results must still come from the API (pinned model, batch).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import time
from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from . import io, params, protocol

# $/MTok (input, output), standard; batch is half. Source: Anthropic price list as of 2026-11-03.
PRICES = {"claude-sonnet-5-5": (2, 10), "claude-opus-5-5": (4, 20),
          "claude-fable-5-2": (8, 40), "claude-fable-5-1": (10, 50)}
# surfaces x K repeats; one chain covers both stages
DESIGNS = {"7 surfaces, K=3": 21, "7 surfaces, K=5": 35}


def call_claude_cli(model: str, effort: str, system: str, user: str, cwd: str, timeout_s: int,
                    resume: str | None = None) -> dict:
    """One turn. Pass the previous turn's session id as `resume` to continue the conversation."""
    env = dict(os.environ, CLAUDE_CODE_MAX_OUTPUT_TOKENS="128000")
    cmd = ["claude", "-p", "--model", model, "--effort", effort, "--system-prompt", system,
           "--tools", "", "--strict-mcp-config", "--output-format", "json"]
    if resume:
        cmd += ["--resume", resume]
    t0 = time.time()
    proc = subprocess.run(cmd, input=user, capture_output=True, text=True, env=env, cwd=cwd,
                          timeout=timeout_s)
    if not proc.stdout.strip():
        raise RuntimeError(f"claude exited {proc.returncode}: {proc.stderr[-2000:]}")
    out = json.loads(proc.stdout)
    out["wall_seconds"] = time.time() - t0
    return out


def tokens(resp: dict) -> dict:
    u = resp.get("usage", {})
    n_in = sum(u.get(k, 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    n_out = u.get("output_tokens", 0)
    think = u.get("output_tokens_details", {}).get("thinking_tokens", 0)
    return {"input": n_in, "output_total": n_out, "thinking": think, "visible": n_out - think}


def projection(input_tokens: int, output_tokens: int) -> dict:
    """Batch cost of one chain, with all input priced at the uncached rate."""
    table = {}
    for model, (pin, pout) in PRICES.items():
        chain = (input_tokens * pin + output_tokens * pout) / 2e6
        table[model] = {"per_chain_batch": chain, **{name: n * chain for name, n in DESIGNS.items()}}
    return table


def figure(z_ref, dx_ref, stages, dx_gen, path, title):
    fig, axes = plt.subplots(1, len(stages) + 2, figsize=(4.6 * (len(stages) + 2), 4.2))
    lim = np.percentile(np.abs(z_ref), 99.5)
    panels = [("measured scan", z_ref, dx_ref)] + [(f"stage {i}", z, dx_gen) for i, z in stages]
    for ax, (name, z, dx) in zip(axes, panels):
        im = ax.imshow(z, cmap="viridis", vmin=-lim, vmax=lim,
                       extent=[0, z.shape[1] * dx / 1000, z.shape[0] * dx / 1000, 0])
        ax.set(title=f"{name}, {z.shape[1]} × {z.shape[0]}", xlabel="x (mm)", ylabel="y (mm)")
        fig.colorbar(im, ax=ax, label="height (µm)", shrink=0.8)
        f, p = params.radial_psd(z, dx)
        axes[-1].loglog(f, p, label=name)
    axes[-1].set(title="radially averaged PSD", xlabel="spatial frequency (1/µm)", ylabel="PSD (µm⁴)")
    axes[-1].grid(alpha=0.3, which="both", lw=0.4)
    axes[-1].legend()
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", default="Sample_23", help="form-removed file name; Sample_23 is Sample_8_13_2.75x")
    ap.add_argument("--grid", type=int, default=200, help="output is grid x grid")
    ap.add_argument("--grid-info", default="scan", choices=protocol.GRID_INFO,
                    help="stage 1 opening line: the scan's size and sampling interval (scan), "
                         "the output grid's sampling interval (output), or nothing (none)")
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--effort", default="medium")
    ap.add_argument("--timeout", type=int, default=5400, help="seconds per stage")
    ap.add_argument("--dry-run", action="store_true", help="print the prompts, do not call a model")
    a = ap.parse_args()

    ref = io.reference(a.sample)
    dx = ref["dx_um"]
    s_um = params.S_FILTER_PIXELS * dx
    z_ref = params.prepare(ref["z_um"], dx, s_um)
    p_ref = params.compute(z_ref, dx)
    dx_out = io.output_pitch(ref, a.grid, "field")
    system = protocol.system_prompt(a.grid)
    n_stages = len(protocol.STAGES)
    header = protocol.grid_header(a.grid_info, a.grid, dx_out, ref["shape"], dx)
    prompts = [protocol.user_prompt(p_ref, s, header) for s in range(1, n_stages + 1)]
    if a.dry_run:
        print("[system]", system, sep="\n")
        for s, text in enumerate(prompts, 1):
            print(f"\n[user, stage {s}]", text, sep="\n")
        return

    run_dir = io.RUNS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}_{a.sample}_chain_g{a.grid}_info-{a.grid_info}_{a.model}_{a.effort}"
    run_dir.mkdir(parents=True)
    (run_dir / "prompt.txt").write_text(
        f"[system]\n{system}\n" + "".join(f"\n[user, stage {s}]\n{t}\n" for s, t in enumerate(prompts, 1)))
    record = {
        "sample": a.sample, "grid": a.grid, "grid_info": a.grid_info, "model": a.model,
        "effort": a.effort, "temperature": "not settable on this model", "client": "claude-code-cli (subscription)",
        "catalog": io.catalog()[a.sample], "scan_shape": ref["shape"], "scan_dx_um": dx,
        "output_dx_um": dx_out, "s_filter_um": s_um, "missing_fraction": ref["missing_fraction"], "stages": [],
    }

    session, surfaces = None, []
    with tempfile.TemporaryDirectory() as cwd:  # empty directory: no project context; shared so stage 2 can resume
        for s, text in enumerate(prompts, 1):
            resp = call_claude_cli(a.model, a.effort, system, text, cwd, a.timeout, resume=session)
            session = resp.get("session_id")
            out = resp.pop("result", "") or ""
            (run_dir / f"response_stage{s}.txt").write_text(out)
            parsed = protocol.parse(out, a.grid)
            stage = {"stage": s, "families": protocol.STAGES[s - 1], "tokens": tokens(resp),
                     "stop_reason": resp.get("stop_reason"), "wall_seconds": resp["wall_seconds"],
                     "cli_reported_cost_usd": resp.get("total_cost_usd"),
                     "parse": {k: parsed.get(k) for k in ("ok", "failure", "strict", "scale")},
                     "cli_response": resp}
            if parsed["ok"]:
                z_gen = params.prepare(parsed["z_um"], dx_out, s_um)
                np.save(run_dir / f"generated_stage{s}.npy", z_gen)
                stage["score"] = protocol.score(p_ref, params.compute(z_gen, dx_out), protocol.given_through(s))
                stage["score"]["psd_log10_rms"] = protocol.psd_distance(z_ref, dx, z_gen, dx_out)
                surfaces.append((s, z_gen))
            record["stages"].append(stage)
            (run_dir / "record.json").write_text(json.dumps(record, indent=2))

    tot_in = sum(st["tokens"]["input"] for st in record["stages"])
    tot_out = sum(st["tokens"]["output_total"] for st in record["stages"])
    record["chain_tokens"] = {"input": tot_in, "output_total": tot_out}
    record["projection_usd"] = projection(tot_in, tot_out)
    (run_dir / "record.json").write_text(json.dumps(record, indent=2))
    if surfaces:
        figure(z_ref, dx, surfaces, dx_out, run_dir / "comparison.png",
               f"{a.sample} ({record['catalog']['process']}), {a.model}, {a.effort} effort, "
               f"grid info: {a.grid_info}")

    print(f"run dir: {run_dir}")
    for st in record["stages"]:
        t = st["tokens"]
        print(f"stage {st['stage']}: input {t['input']}, output {t['output_total']} (thinking {t['thinking']}); "
              f"stop={st['stop_reason']}; {st['wall_seconds']:.0f} s; parse {st['parse']}")
    scored = [st for st in record["stages"] if "score" in st]
    if scored:
        print(f"{'param':6s} {'target':>10s} " + " ".join(f"{'stage ' + str(st['stage']):>20s}" for st in scored))
        for name in p_ref:
            cells = []
            for st in scored:
                v = st["score"]["per_param"][name]
                cells.append(f"{v['generated']:10.4g} {v['rel_error']:6.2f} {'g' if v['provided'] else ' '}")
            print(f"{name:6s} {p_ref[name]:10.4g} " + " ".join(f"{c:>20s}" for c in cells))
        for fam in params.FAMILIES:
            print(f"family {fam:10s} " + " | ".join(
                f"stage {st['stage']}: median {st['score']['families'][fam]['median_rel_error']:.2f}, "
                f"{st['score']['families'][fam]['recovered']}/{st['score']['families'][fam]['n']} within 10%"
                for st in scored))
        print("PSD difference: " + ", ".join(f"stage {st['stage']} {st['score']['psd_log10_rms']:.2f}" for st in scored))
    print(f"chain tokens: input {tot_in}, output {tot_out}; projected batch cost (USD):")
    for model, row in record["projection_usd"].items():
        print(f"  {model:18s} per chain ${row['per_chain_batch']:.2f} | " +
              " | ".join(f"{k}: ${row[k]:.0f}" for k in DESIGNS))


if __name__ == "__main__":
    main()
