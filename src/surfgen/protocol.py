"""Prompt construction, output parsing and scoring.

Design as of 2026-11-17: one conversation per surface, two stages. Stage 1 gives the
height and functional/volume families; stage 2 adds spatial, hybrid and feature in the
same conversation. Stage 1 opens with the scan's size and sampling interval; no levelling is stated.
"""
from __future__ import annotations

import numpy as np

from .params import FAMILIES, INFO, radial_psd

STAGES = [["height", "functional"], ["spatial", "hybrid", "feature"]]


def system_prompt(grid: int) -> str:
    return (
        "You are generating a synthetic areal surface height map. You will be given ISO 25178-2 "
        "surface texture parameters measured from a real surface, along with the measurement grid. "
        "Produce a surface whose parameters, when measured the same way, match the given values as "
        "closely as possible.\n\n"
        "Output format, strictly:\n"
        "Line 1: SCALE <z_min_um> <z_max_um> giving the physical heights that integer 0 and integer "
        "1000 map to.\n"
        f"Lines 2–{grid + 1}: {grid} rows of {grid} comma-separated integers from 0 to 1000. Start "
        f"each row with its row label and a colon, R001: for the first row through R{grid:03d}: for "
        "the last.\n"
        "No other text, code, explanation, markdown."
    )


def stage_params(stage: int) -> list[str]:
    """Parameters introduced at this stage (1-based)."""
    return [p for fam in STAGES[stage - 1] for p in FAMILIES[fam]]


def given_through(stage: int) -> list[str]:
    return [p for s in range(1, stage + 1) for p in stage_params(s)]


GRID_INFO = ("scan", "output", "none")


def grid_header(mode: str, grid: int, dx_out: float, scan_shape, scan_dx: float) -> str | None:
    """Opening line of stage 1: what the model is told about spacing."""
    if mode == "scan":
        return (f"The original scan is {scan_shape[1]} × {scan_shape[0]} points with a sampling interval of "
                f"{scan_dx:.4g} µm. Your {grid} × {grid} height map covers the same area.")
    if mode == "output":
        return f"Grid: {grid} × {grid} points, sampling interval {dx_out:.4g} µm in x and y."
    if mode == "none":
        return None
    raise ValueError(mode)


def user_prompt(params: dict, stage: int, header: str | None = None) -> str:
    """Stage prompt. The header, if any, opens stage 1."""
    lines = []
    if stage == 1 and header:
        lines += [header, ""]
    lines.append("Parameters (ISO 25178-2):" if stage == 1 else "Additional parameters (ISO 25178-2):")
    for name in stage_params(stage):
        unit, definition = INFO[name]
        lines.append(f"{name} = {params[name]:.4g}{' ' + unit if unit else ''} — {definition}")
    lines += ["", "Generate the height map." if stage == 1 else
              "Generate the height map again so that all parameters given so far are matched."]
    return "\n".join(lines)


def parse(text: str, grid: int) -> dict:
    """Parse the output contract. Returns ok / failure / strict / scale / z_um."""
    raw = text.strip().splitlines()
    lines = [ln.strip() for ln in raw if ln.strip() and not ln.strip().startswith("```")]
    start = next((i for i, ln in enumerate(lines) if ln.upper().startswith("SCALE")), None)
    if start is None:
        return {"ok": False, "failure": "no_scale_line"}
    strict = start == 0 and len(lines) == len(raw) == grid + 1
    try:
        z0, z1 = (float(v) for v in lines[start].split()[1:3])
    except ValueError:
        return {"ok": False, "failure": "bad_scale_line"}
    body = lines[start + 1:]
    if len(body) != grid:
        return {"ok": False, "failure": f"row_count_{len(body)}"}
    rows = []
    for i, ln in enumerate(body):
        label, sep, ln = ln.partition(":")
        if not sep or label.strip().upper() != f"R{i + 1:03d}":
            return {"ok": False, "failure": f"row_label_row_{i}"}
        cells = [c.strip() for c in ln.rstrip(",").split(",")]
        if len(cells) != grid:
            return {"ok": False, "failure": f"col_count_{len(cells)}_row_{i}"}
        try:
            rows.append([int(c) for c in cells])
        except ValueError:
            return {"ok": False, "failure": f"non_integer_row_{i}"}
    g = np.array(rows, dtype=float)
    if g.min() < 0 or g.max() > 1000:
        return {"ok": False, "failure": "out_of_range"}
    return {"ok": True, "failure": None, "strict": strict, "scale": [z0, z1],
            "z_um": z0 + g / 1000.0 * (z1 - z0)}


def psd_distance(z_ref, dx_ref, z_gen, dx_gen) -> float:
    """RMS log10 ratio of the radial PSDs over the frequency band both surfaces resolve."""
    fr, pr = radial_psd(z_ref, dx_ref)
    fg, pg = radial_psd(z_gen, dx_gen)
    band = (fg >= fr[0]) & (fg <= fr[-1]) & (pg > 0)
    if not band.any():
        return float("nan")
    ref_at = np.interp(np.log10(fg[band]), np.log10(fr), np.log10(np.maximum(pr, 1e-300)))
    return float(np.sqrt(np.mean((np.log10(pg[band]) - ref_at) ** 2)))


def score(ref: dict, gen: dict, given_names) -> dict:
    given = set(given_names)
    per_param = {}
    for name, target in ref.items():
        got = gen[name]
        if name == "Std":  # angular, scaled so 90 degrees off = 1
            d = abs(got - target) % 180
            err = min(d, 180 - d) / 90
        else:
            err = abs(got - target) / abs(target) if abs(target) > 1e-12 else float("nan")
        per_param[name] = {"target": target, "generated": got, "rel_error": err,
                           "provided": name in given, "recovered": bool(err <= 0.10)}
    families = {}
    for fam, names in FAMILIES.items():
        errs = [per_param[n]["rel_error"] for n in names]
        families[fam] = {"provided": names[0] in given, "mean_rel_error": float(np.nanmean(errs)),
                         "median_rel_error": float(np.nanmedian(errs)),
                         "recovered": int(sum(per_param[n]["recovered"] for n in names)), "n": len(names)}
    return {"per_param": per_param, "families": families}
