"""Prompt construction, output parsing and scoring, as fixed in docs/outline.pdf."""
from __future__ import annotations

import numpy as np

from .params import FAMILIES, INFO, LEVELS, S_FILTER_PIXELS, radial_psd

SYSTEM_PROMPT = (
    "You are generating a synthetic areal surface height map. You will be given ISO 25178-2 "
    "surface texture parameters measured from a real surface, along with the measurement grid. "
    "Produce a surface whose parameters, when measured the same way, match the given values as "
    "closely as possible.\n\n"
    "Output format, strictly:\n"
    "Line 1: SCALE <z_min_um> <z_max_um> giving the physical heights that integer 0 and integer "
    "1000 map to.\n"
    "Lines 2–129: 128 rows of 128 comma-separated integers from 0 to 1000.\n"
    "No other text, code, explanation, markdown."
)


def provided(level: int) -> list[str]:
    return [p for fam in LEVELS[:level] for p in FAMILIES[fam]]


def user_prompt(params: dict, dx_um: float, level: int) -> str:
    s_um = S_FILTER_PIXELS * dx_um
    lines = [
        f"Grid: 128 × 128 points, sampling interval {dx_um:.4g} µm in x and y. The surface was "
        f"levelled and filtered with [S-filter: Gaussian, nesting index {s_um:.4g} µm; F-operation: "
        f"least-squares plane; L-filter: none] before parameters were computed.",
        "",
        "Parameters (ISO 25178-2):",
    ]
    for name in provided(level):
        unit, definition = INFO[name]
        lines.append(f"{name} = {params[name]:.4g}{' ' + unit if unit else ''} — {definition}")
    lines += ["", "Generate the height map."]
    return "\n".join(lines)


def parse(text: str) -> dict:
    """Parse the output contract. Returns ok / failure / strict / scale / z_um."""
    raw = text.strip().splitlines()
    lines = [ln.strip() for ln in raw if ln.strip() and not ln.strip().startswith("```")]
    start = next((i for i, ln in enumerate(lines) if ln.upper().startswith("SCALE")), None)
    if start is None:
        return {"ok": False, "failure": "no_scale_line"}
    strict = start == 0 and len(lines) == len(raw) == 129
    try:
        z0, z1 = (float(v) for v in lines[start].split()[1:3])
    except ValueError:
        return {"ok": False, "failure": "bad_scale_line"}
    body = lines[start + 1:]
    if len(body) != 128:
        return {"ok": False, "failure": f"row_count_{len(body)}"}
    grid = []
    for i, ln in enumerate(body):
        cells = [c.strip() for c in ln.rstrip(",").split(",")]
        if len(cells) != 128:
            return {"ok": False, "failure": f"col_count_{len(cells)}_row_{i}"}
        try:
            grid.append([int(c) for c in cells])
        except ValueError:
            return {"ok": False, "failure": f"non_integer_row_{i}"}
    g = np.array(grid, dtype=float)
    if g.min() < 0 or g.max() > 1000:
        return {"ok": False, "failure": "out_of_range"}
    return {"ok": True, "failure": None, "strict": strict, "scale": [z0, z1],
            "z_um": z0 + g / 1000.0 * (z1 - z0)}


def score(ref: dict, gen: dict, level: int, z_ref: np.ndarray, z_gen: np.ndarray) -> dict:
    given = set(provided(level))
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
    pr, pg = radial_psd(z_ref), radial_psd(z_gen)
    with np.errstate(divide="ignore", invalid="ignore"):
        d = np.log10(pg) - np.log10(pr)
    psd = float(np.sqrt(np.mean(d[np.isfinite(d)] ** 2))) if np.isfinite(d).any() else float("nan")
    return {"per_param": per_param, "families": families, "psd_log10_rms": psd}
