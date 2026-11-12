"""One stateless generation, scored, with a budget projection from the measured tokens.

    python -I -m surfgen.pilot --sample Sample_21 --condition coarse --level 5

Client: the Claude Code CLI in print mode, billed to the claude.ai subscription rather
than the API. It sends the same system and user prompt with no tools, so token counts
transfer to the API; reported results must still come from the API (pinned model, batch).
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
DESIGNS = {"K=3, one native patch": 360, "K=5, one native patch": 600, "K=5, three native patches": 1200}


def call_claude_cli(model: str, effort: str, system: str, user: str, timeout_s: int) -> dict:
    env = dict(os.environ, CLAUDE_CODE_MAX_OUTPUT_TOKENS="128000")
    cmd = ["claude", "-p", "--model", model, "--effort", effort, "--system-prompt", system,
           "--tools", "", "--strict-mcp-config", "--output-format", "json"]
    with tempfile.TemporaryDirectory() as cwd:  # empty directory: no project context is attached
        t0 = time.time()
        proc = subprocess.run(cmd, input=user, capture_output=True, text=True, env=env, cwd=cwd,
                              timeout=timeout_s)
    if proc.returncode != 0 and not proc.stdout.strip():
        raise RuntimeError(f"claude exited {proc.returncode}: {proc.stderr[-2000:]}")
    out = json.loads(proc.stdout)
    out["wall_seconds"] = time.time() - t0
    return out


def projection(input_tokens: int, output_tokens: int) -> dict:
    table = {}
    for model, (pin, pout) in PRICES.items():
        per_run = (input_tokens * pin + output_tokens * pout) / 1e6
        table[model] = {"per_run_standard": per_run, "per_run_batch": per_run / 2,
                        **{name: runs * per_run / 2 for name, runs in DESIGNS.items()}}
    return table


def figure(z_ref, z_gen, dx, path, title):
    fig, axes = plt.subplots(1, 3, figsize=(13, 4))
    lim = np.percentile(np.abs(z_ref), 99.5)
    extent = [0, z_ref.shape[1] * dx, z_ref.shape[0] * dx, 0]
    for ax, z, name in ((axes[0], z_ref, "reference"), (axes[1], z_gen, "generated")):
        im = ax.imshow(z, cmap="viridis", vmin=-lim, vmax=lim, extent=extent)
        ax.set(title=name, xlabel="x (µm)", ylabel="y (µm)")
        fig.colorbar(im, ax=ax, label="height (µm)", shrink=0.8)
    for z, name in ((z_ref, "reference"), (z_gen, "generated")):
        psd = params.radial_psd(z)
        axes[2].loglog(np.arange(1, psd.size + 1) / (z.shape[0] * dx), psd, label=name)
    axes[2].set(title="radially averaged PSD", xlabel="spatial frequency (1/µm)", ylabel="power (a.u.)")
    axes[2].legend()
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", default="Sample_21")
    ap.add_argument("--condition", default="coarse", choices=["coarse", "native"])
    ap.add_argument("--level", type=int, default=5, choices=range(1, 6))
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--effort", default="medium")
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--dry-run", action="store_true", help="build and print the prompt, do not call a model")
    a = ap.parse_args()

    ref = io.reference(a.sample, a.condition)
    dx = ref["dx_um"]
    z_ref = params.prepare(ref["z_um"], dx)
    p_ref = params.compute(z_ref, dx)
    user = protocol.user_prompt(p_ref, dx, a.level)
    if a.dry_run:
        print(protocol.SYSTEM_PROMPT, "\n---\n", user, sep="")
        return

    run_dir = io.RUNS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}_{a.sample}_{a.condition}_L{a.level}_{a.model}"
    run_dir.mkdir(parents=True)
    (run_dir / "prompt.txt").write_text(f"[system]\n{protocol.SYSTEM_PROMPT}\n\n[user]\n{user}\n")
    np.save(run_dir / "reference.npy", z_ref)

    resp = call_claude_cli(a.model, a.effort, protocol.SYSTEM_PROMPT, user, a.timeout)
    text = resp.pop("result", "") or ""
    (run_dir / "response.txt").write_text(text)
    usage = resp.get("usage", {})
    n_in = sum(usage.get(k, 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    n_out = usage.get("output_tokens", 0)
    n_think = usage.get("output_tokens_details", {}).get("thinking_tokens", 0)
    record = {
        "sample": a.sample, "condition": a.condition, "level": a.level, "model": a.model,
        "effort": a.effort, "temperature": "not settable on this model", "client": "claude-code-cli (subscription)",
        "catalog": io.catalog()[a.sample], "dx_um": dx, "location": ref["location"],
        "s_filter_pixels": params.S_FILTER_PIXELS,
        "tokens": {"input": n_in, "output_total": n_out, "thinking": n_think, "visible": n_out - n_think},
        "stop_reason": resp.get("stop_reason"), "wall_seconds": resp["wall_seconds"],
        "cli_reported_cost_usd": resp.get("total_cost_usd"),
        "projection_usd": projection(n_in, n_out), "cli_response": resp,
    }

    parsed = protocol.parse(text)
    record["parse"] = {k: parsed.get(k) for k in ("ok", "failure", "strict", "scale")}
    if parsed["ok"]:
        z_gen = params.prepare(parsed["z_um"], dx)
        np.save(run_dir / "generated.npy", z_gen)
        record["score"] = protocol.score(p_ref, params.compute(z_gen, dx), a.level, z_ref, z_gen)
        figure(z_ref, z_gen, dx, run_dir / "comparison.png",
               f"{a.sample} ({record['catalog']['process']}), {a.condition}, level {a.level}, {a.model}")
    (run_dir / "record.json").write_text(json.dumps(record, indent=2))

    t = record["tokens"]
    print(f"run dir: {run_dir}")
    print(f"tokens: input {t['input']}, output {t['output_total']} (thinking {t['thinking']}, visible {t['visible']}); "
          f"stop={record['stop_reason']}; {record['wall_seconds']:.0f} s; CLI cost estimate ${record['cli_reported_cost_usd']}")
    print(f"parse: {record['parse']}")
    if parsed["ok"]:
        print(f"{'param':6s} {'target':>10s} {'generated':>10s} {'rel err':>8s}  given")
        for name, s in record["score"]["per_param"].items():
            print(f"{name:6s} {s['target']:10.4g} {s['generated']:10.4g} {s['rel_error']:8.2f}  {'yes' if s['provided'] else 'no'}")
        for fam, s in record["score"]["families"].items():
            print(f"family {fam:10s} mean err {s['mean_rel_error']:.2f}  recovered {s['recovered']}/{s['n']}")
        print(f"PSD log10 RMS difference: {record['score']['psd_log10_rms']:.2f}")
    print("projected batch cost (USD) at these token counts:")
    for model, row in record["projection_usd"].items():
        print(f"  {model:18s} per run ${row['per_run_batch']:.3f} | " +
              " | ".join(f"{k}: ${row[k]:.0f}" for k in DESIGNS))


if __name__ == "__main__":
    main()
