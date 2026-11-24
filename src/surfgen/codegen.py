"""Code-generation condition: a model writes one program; we run every surface through it.

    python -I -m surfgen.codegen write  --model claude-opus-5-5          # model writes and tests its program
    python -I -m surfgen.codegen apply  RUN_DIR --samples Sample_23 ...  # run the program on surfaces and score

The program is written once, in an isolated conversation, from parameter definitions and one
example surface's values. It produces two height maps per surface: stage 1 from the height and
functional/volume parameters, stage 2 built on it from all parameters. Output is at the scan's
own size and sampling interval. Model-written code runs in a bubblewrap sandbox: no network,
no home directory, read-only system, one scratch directory.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from . import io, params, protocol
from .params import FAMILIES, INFO

STAGE1_FAMILIES = ["height", "functional"]
STAGE2_FAMILIES = ["spatial", "hybrid", "feature"]
EXAMPLE_SAMPLE = "Sample_23"
TIME_LIMIT_MIN = 10
MAX_TEST_RUNS = 5
PRICES = {"claude-sonnet-5-5": (2, 10), "claude-opus-5-5": (4, 20),
          "claude-fable-5-2": (8, 40), "claude-fable-5-1": (10, 50)}  # $/MTok standard, 2026-11-03

SYSTEM_PROMPT = f"""You are writing a program that generates synthetic areal surface height maps. The program will be given ISO 25178-2 surface texture parameters measured from a real surface, along with the measurement grid. It must produce a surface whose parameters, when measured the same way, match the given values as closely as possible. Make the surface however you want.

The program is written once and then run unchanged on many different surfaces, each with its own parameter values and grid. An example from one surface is given below; the program must work for any values. It is run several times on each surface, and each run should give a different surface.

For each surface the program produces two height maps:
Stage 1: made from the height and functional/volume parameters only.
Stage 2: built on the stage 1 height map, using all the parameters.

How it is run: Python 3 with numpy and scipy, as `python program.py input.json output_dir`. input.json has the keys rows, cols, dx_um (sampling interval in µm), stage1_params and stage2_params (parameter name to value; stage2_params holds the parameters added at stage 2). The program writes output_dir/stage1.csv and output_dir/stage2.csv, each with rows lines of cols comma-separated heights in µm. It has up to {TIME_LIMIT_MIN} minutes per surface.

You may test before submitting: reply with the complete program in one python code block and it will be run on the example, and whatever it prints will be returned to you. When you are satisfied, reply with the final program in one python code block followed by the word FINAL on its own line. You have at most {MAX_TEST_RUNS} test runs."""


def _names(families):
    return [p for fam in families for p in FAMILIES[fam]]


def _lines(p: dict, families) -> list[str]:
    out = []
    for name in _names(families):
        unit, definition = INFO[name]
        out.append(f"{name} = {p[name]:.4g}{' ' + unit if unit else ''} — {definition}")
    return out


def example_prompt(ref: dict, p: dict) -> str:
    rows, cols = ref["shape"]
    return "\n".join(
        [f"Example grid: {cols} × {rows} points, sampling interval {ref['dx_um']:.4g} µm.", "",
         "Height and functional/volume parameters (stage1_params):"] + _lines(p, STAGE1_FAMILIES)
        + ["", "Spatial, hybrid and feature parameters (stage2_params):"] + _lines(p, STAGE2_FAMILIES))


def surface_input(ref: dict, p: dict) -> dict:
    rows, cols = ref["shape"]
    return {"rows": rows, "cols": cols, "dx_um": ref["dx_um"],
            "stage1_params": {n: p[n] for n in _names(STAGE1_FAMILIES)},
            "stage2_params": {n: p[n] for n in _names(STAGE2_FAMILIES)}}


def target(sample: str):
    ref = io.reference(sample)
    z = params.prepare(ref["z_um"], ref["dx_um"], params.S_FILTER_PIXELS * ref["dx_um"])
    return ref, z, params.compute(z, ref["dx_um"])


# ---------------------------------------------------------------- sandbox

def run_program(program: Path, inp: dict, out_dir: Path, limit_s: int) -> dict:
    """Run a model-written program in a sandbox. Returns exit status, output text and timing."""
    out_dir.mkdir(parents=True, exist_ok=True)
    venv = Path(sys.prefix)
    py_root = Path(os.path.realpath(sys.executable)).parents[2]  # uv's python install directory
    with tempfile.TemporaryDirectory() as work:
        work = Path(work)
        shutil.copy(program, work / "program.py")
        (work / "input.json").write_text(json.dumps(inp))
        (work / "out").mkdir()
        cmd = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
               "--tmpfs", "/home", "--ro-bind", str(venv), str(venv), "--ro-bind", str(py_root), str(py_root),
               "--bind", str(work), "/tmp/work", "--unshare-net", "--unshare-pid", "--die-with-parent",
               "--chdir", "/tmp/work", str(venv / "bin" / "python"), "-I", "program.py", "input.json", "out"]
        t0 = time.time()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=limit_s)
            code, out, err, timed_out = proc.returncode, proc.stdout, proc.stderr, False
        except subprocess.TimeoutExpired as e:
            code, timed_out = None, True
            out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            err = e.stderr.decode(errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
        seconds = time.time() - t0
        files = {}
        for s in (1, 2):
            src = work / "out" / f"stage{s}.csv"
            if src.exists():
                shutil.copy(src, out_dir / src.name)
                files[s] = out_dir / src.name
    return {"exit_code": code, "timed_out": timed_out, "seconds": seconds, "stdout": out, "stderr": err, "files": files}


def load_surface(path: Path, rows: int, cols: int):
    """Returns (array, None) or (None, reason)."""
    try:
        z = np.loadtxt(path, delimiter=",", ndmin=2)
    except Exception as e:  # malformed file written by the program
        return None, f"unreadable ({type(e).__name__})"
    if z.shape != (rows, cols):
        return None, f"shape {z.shape[1]} × {z.shape[0]}, expected {cols} × {rows}"
    if not np.isfinite(z).all():
        return None, "contains non-finite values"
    return z, None


def _clip(text: str, n: int = 6000) -> str:
    return text if len(text) <= n else text[:n // 2] + f"\n... [{len(text) - n} characters omitted] ...\n" + text[-n // 2:]


def test_feedback(res: dict, inp: dict) -> str:
    """What the model is told after a test run: its own output and whether the files are well formed."""
    lines = [f"Run time: {res['seconds']:.0f} s." + (f" Stopped at the {TIME_LIMIT_MIN}-minute limit." if res["timed_out"] else
                                                     f" Exit code {res['exit_code']}.")]
    for s in (1, 2):
        if s not in res["files"]:
            lines.append(f"stage{s}.csv: not written.")
        else:
            z, why = load_surface(res["files"][s], inp["rows"], inp["cols"])
            lines.append(f"stage{s}.csv: " + ("written, correct size." if z is not None else why + "."))
    lines += ["", "Printed output:", _clip(res["stdout"]) or "(nothing)"]
    if res["stderr"].strip():
        lines += ["", "Error output:", _clip(res["stderr"])]
    return "\n".join(lines)


# ---------------------------------------------------------------- model conversation

def call_claude_cli(model, effort, system, user, cwd, resume=None, timeout_s=3600) -> dict:
    env = dict(os.environ, CLAUDE_CODE_MAX_OUTPUT_TOKENS="128000")
    cmd = ["claude", "-p", "--model", model, "--effort", effort, "--system-prompt", system,
           "--tools", "", "--strict-mcp-config", "--output-format", "json"]
    if resume:
        cmd += ["--resume", resume]
    t0 = time.time()
    proc = subprocess.run(cmd, input=user, capture_output=True, text=True, env=env, cwd=cwd, timeout=timeout_s)
    if not proc.stdout.strip():
        raise RuntimeError(f"claude exited {proc.returncode}: {proc.stderr[-2000:]}")
    out = json.loads(proc.stdout)
    out["wall_seconds"] = time.time() - t0
    return out


def extract_program(text: str) -> str | None:
    blocks = re.findall(r"```(?:python|py)?[ \t]*\n(.*?)```", text, flags=re.S)
    return max(blocks, key=len) if blocks else None


def write(a):
    ref, _, p = target(EXAMPLE_SAMPLE)
    inp = surface_input(ref, p)
    user = example_prompt(ref, p)
    run_dir = io.RUNS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}_codegen_{a.model}_{a.effort}"
    run_dir.mkdir(parents=True)
    (run_dir / "prompt.txt").write_text(f"[system]\n{SYSTEM_PROMPT}\n\n[user]\n{user}\n")
    if a.dry_run:
        print((run_dir / "prompt.txt").read_text())
        shutil.rmtree(run_dir)
        return
    record = {"model": a.model, "effort": a.effort, "client": "claude-code-cli (subscription)",
              "example_sample": EXAMPLE_SAMPLE, "time_limit_min": TIME_LIMIT_MIN, "max_test_runs": MAX_TEST_RUNS,
              "turns": [], "final": False}
    session, message, program = None, user, None
    with tempfile.TemporaryDirectory() as cwd:  # empty directory, fresh session: no memory of anything else
        for turn in range(1, MAX_TEST_RUNS + 2):
            resp = call_claude_cli(a.model, a.effort, SYSTEM_PROMPT, message, cwd, resume=session)
            session = resp.get("session_id")
            text = resp.pop("result", "") or ""
            (run_dir / f"reply_{turn}.md").write_text(text)
            u = resp.get("usage", {})
            t = {"turn": turn, "input": sum(u.get(k, 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")),
                 "output": u.get("output_tokens", 0),
                 "thinking": u.get("output_tokens_details", {}).get("thinking_tokens", 0),
                 "wall_seconds": resp["wall_seconds"], "stop_reason": resp.get("stop_reason"),
                 "safety_stops": resp.get("safety_stops", 0)}
            code = extract_program(text)
            if code:
                program = run_dir / f"program_{turn}.py"
                program.write_text(code)
            final = bool(re.search(r"^\s*FINAL\s*$", text, flags=re.M))
            t.update(has_program=bool(code), said_final=final)
            record["turns"].append(t)
            print(f"turn {turn}: output {t['output']} tokens (thinking {t['thinking']}), program {'yes' if code else 'NO'}, final {final}")
            if final and code:
                record["final"] = True
                break
            if turn > MAX_TEST_RUNS:
                break
            if not code:
                message = "No python code block was found in your reply. Reply with the complete program in one python code block."
            else:
                res = run_program(program, inp, run_dir / f"test_{turn}", TIME_LIMIT_MIN * 60)
                message = test_feedback(res, inp)
                t["test"] = {k: res[k] for k in ("exit_code", "timed_out", "seconds")}
                left = MAX_TEST_RUNS - turn
                message += (f"\n\nYou have {left} test run{'s' if left != 1 else ''} left." if left else
                            "\n\nYou have no test runs left. Reply with the final program and FINAL.")
            (run_dir / f"feedback_{turn}.txt").write_text(message)
            (run_dir / "record.json").write_text(json.dumps(record, indent=2))
    if program:
        shutil.copy(program, run_dir / "program_final.py")
    n_in = sum(t["input"] for t in record["turns"])
    n_out = sum(t["output"] for t in record["turns"])
    record["tokens"] = {"input": n_in, "output": n_out}
    if a.model in PRICES:
        pin, pout = PRICES[a.model]
        record["cost_usd_standard"] = (n_in * pin + n_out * pout) / 1e6
    (run_dir / "record.json").write_text(json.dumps(record, indent=2))
    print(f"run dir: {run_dir}")
    print(f"turns {len(record['turns'])}, final declared: {record['final']}, tokens in {n_in} out {n_out}"
          + (f", API cost ${record['cost_usd_standard']:.2f} standard" if "cost_usd_standard" in record else ""))


# ---------------------------------------------------------------- apply and score

def figure(z_ref, dx, stages, path, title):
    fig, axes = plt.subplots(1, len(stages) + 2, figsize=(4.6 * (len(stages) + 2), 4.2))
    lim = np.percentile(np.abs(z_ref), 99.5)
    for ax, (name, z) in zip(axes, [("measured scan", z_ref)] + [(f"stage {s}", z) for s, z in stages]):
        im = ax.imshow(z, cmap="viridis", vmin=-lim, vmax=lim, extent=[0, z.shape[1] * dx / 1000, z.shape[0] * dx / 1000, 0])
        ax.set(title=f"{name}, {z.shape[1]} × {z.shape[0]}", xlabel="x (mm)", ylabel="y (mm)")
        fig.colorbar(im, ax=ax, label="height (µm)", shrink=0.8)
        f, pw = params.radial_psd(z, dx)
        axes[-1].loglog(f, pw, label=name)
    axes[-1].set(title="radially averaged PSD", xlabel="spatial frequency (1/µm)", ylabel="PSD (µm⁴)")
    axes[-1].grid(alpha=0.3, which="both", lw=0.4)
    axes[-1].legend()
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def apply(a):
    run_dir = Path(a.run_dir)
    program = run_dir / "program_final.py"
    rec = json.loads((run_dir / "record.json").read_text())
    given = {1: _names(STAGE1_FAMILIES), 2: _names(STAGE1_FAMILIES + STAGE2_FAMILIES)}
    out_root = run_dir / "surfaces"
    rows_out, summary = [], []
    for sample in a.samples:
        ref, z_ref, p_ref = target(sample)
        dx = ref["dx_um"]
        inp = surface_input(ref, p_ref)
        (out_root / sample).mkdir(parents=True, exist_ok=True)
        np.savetxt(out_root / sample / "measured.csv", z_ref, delimiter=",", fmt="%.6f")
        f, pw = params.radial_psd(z_ref, dx)
        psd_rows = [("measured", 0, fi, pi) for fi, pi in zip(f, pw)]
        for rep in range(a.repeats):
            d = out_root / sample / f"run{rep + 1}"
            res = run_program(program, inp, d, TIME_LIMIT_MIN * 60)
            (d / "log.txt").write_text(f"exit {res['exit_code']} timed_out {res['timed_out']} seconds {res['seconds']:.1f}\n"
                                       f"--- stdout\n{res['stdout']}\n--- stderr\n{res['stderr']}")
            shown = []
            for s in (1, 2):
                entry = {"sample": sample, "run": rep + 1, "stage": s, "seconds": round(res["seconds"], 1), "valid": False}
                z, why = (None, "not written") if s not in res["files"] else load_surface(res["files"][s], *ref["shape"])
                if z is None:
                    entry["failure"] = "timed out" if res["timed_out"] else why
                    summary.append(entry)
                    continue
                zg = params.prepare(z, dx, params.S_FILTER_PIXELS * dx)
                sc = protocol.score(p_ref, params.compute(zg, dx), given[s])
                entry.update(valid=True, psd_log10_rms=protocol.psd_distance(z_ref, dx, zg, dx),
                             within10=sum(v["recovered"] for v in sc["families"].values()),
                             families={k: {"median": v["median_rel_error"], "within10": v["recovered"], "n": v["n"]}
                                       for k, v in sc["families"].items()})
                summary.append(entry)
                for name, v in sc["per_param"].items():
                    rows_out.append([sample, rep + 1, s, name, v["target"], v["generated"], v["rel_error"], int(v["provided"])])
                fg, pg = params.radial_psd(zg, dx)
                psd_rows += [(f"stage{s}", rep + 1, fi, pi) for fi, pi in zip(fg, pg)]
                shown.append((s, zg))
            if rep == 0 and shown:
                figure(z_ref, dx, shown, out_root / sample / "comparison.png",
                       f"{sample} ({io.catalog()[sample]['process']}), code written by {rec['model']}, run 1")
            ok = [e for e in summary if e["sample"] == sample and e["run"] == rep + 1]
            print(f"{sample} run {rep + 1}: {res['seconds']:.0f} s; " + "; ".join(
                f"stage {e['stage']} " + (f"{e['within10']}/28 within 10%, PSD {e['psd_log10_rms']:.2f}" if e["valid"] else f"FAILED ({e['failure']})")
                for e in ok))
        with open(out_root / sample / "psd.csv", "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["surface", "run", "spatial_frequency_per_um", "psd_um4"])
            w.writerows(psd_rows)
    with open(run_dir / "parameters.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["sample", "run", "stage", "parameter", "target", "generated", "relative_error", "given_at_this_stage"])
        w.writerows(rows_out)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"wrote {run_dir / 'parameters.csv'} and {run_dir / 'summary.json'}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write", help="have a model write and test its program")
    w.add_argument("--model", default="claude-opus-5-5")
    w.add_argument("--effort", default="medium")
    w.add_argument("--dry-run", action="store_true", help="print the prompt and stop")
    w.set_defaults(func=write)
    r = sub.add_parser("apply", help="run a written program on surfaces and score it")
    r.add_argument("run_dir")
    r.add_argument("--samples", nargs="+", required=True)
    r.add_argument("--repeats", type=int, default=3)
    r.set_defaults(func=apply)
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
