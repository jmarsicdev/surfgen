"""Load Zygo .datx scans and cut the two 128 x 128 reference conditions."""
from __future__ import annotations

import csv
import os
from pathlib import Path

import h5py
import numpy as np
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = Path(os.environ.get("SURFGEN_RAW", ROOT / "data" / "raw" / "Renamed files"))
RUNS_DIR = Path(os.environ.get("SURFGEN_RUNS", ROOT / "runs"))
CATALOG = ROOT / "data" / "catalog" / "references.csv"
GRID = 128

_UNIT_TO_UM = {"NanoMeters": 1e-3, "MicroMeters": 1.0, "Meters": 1e6, "Angstroms": 1e-4}


def _s(v):
    v = v[0] if isinstance(v, np.ndarray) else v
    return v.decode() if isinstance(v, bytes) else str(v)


def load_datx(path: Path) -> tuple[np.ndarray, float]:
    """Return (heights in micrometres with NaN for missing data, pixel pitch in micrometres)."""
    with h5py.File(path, "r") as f:
        group = f["Data/Surface"]
        ds = group[next(iter(group.keys()))]
        z = ds[...].astype(np.float64)
        no_data = float(ds.attrs["No Data"][0])
        unit = _s(ds.attrs["Unit"])
        dx_m = float(ds.attrs["X Converter"][0]["Parameters"][1])
    z[z >= no_data * 0.99] = np.nan
    if unit not in _UNIT_TO_UM:
        raise ValueError(f"{path.name}: unhandled height unit {unit!r}")
    return z * _UNIT_TO_UM[unit], dx_m * 1e6


def fill_missing(z: np.ndarray) -> np.ndarray:
    """Replace NaN with the nearest valid height."""
    bad = np.isnan(z)
    if not bad.any():
        return z
    idx = ndimage.distance_transform_edt(bad, return_distances=False, return_indices=True)
    return z[tuple(idx)]


def catalog() -> dict[str, dict]:
    with open(CATALOG, newline="") as fh:
        return {row["sample"]: row for row in csv.DictReader(fh)}


def reference(sample: str, condition: str) -> dict:
    """Cut one reference surface.

    coarse: central crop block-averaged to 128 x 128 (pitch = factor x instrument pitch).
    native: central 128 x 128 crop at the instrument pitch.
    """
    z, dx = load_datx(RAW_DIR / f"{sample}.datx")
    missing = float(np.isnan(z).mean())
    rows, cols = z.shape
    if condition == "coarse":
        k = min(rows, cols) // GRID
        r0, c0 = (rows - k * GRID) // 2, (cols - k * GRID) // 2
        crop = z[r0:r0 + k * GRID, c0:c0 + k * GRID]
        with np.errstate(invalid="ignore"):
            out = np.nanmean(crop.reshape(GRID, k, GRID, k), axis=(1, 3))
        out, dx_out = fill_missing(out), dx * k
        loc = {"row0": r0, "col0": c0, "block": k}
    elif condition == "native":
        r0, c0 = (rows - GRID) // 2, (cols - GRID) // 2
        out, dx_out = fill_missing(z)[r0:r0 + GRID, c0:c0 + GRID], dx
        loc = {"row0": r0, "col0": c0, "block": 1}
    else:
        raise ValueError(condition)
    return {"sample": sample, "condition": condition, "z_um": out, "dx_um": dx_out,
            "scan_shape": [rows, cols], "scan_dx_um": dx, "missing_fraction": missing, "location": loc}
