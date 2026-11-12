"""Load Zygo .datx scans. The reference surface is the whole form-removed scan."""
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


def reference(sample: str) -> dict:
    """The whole scan at the instrument pitch, missing points filled; no cropping or resampling."""
    z, dx = load_datx(RAW_DIR / f"{sample}.datx")
    return {"sample": sample, "z_um": fill_missing(z), "dx_um": dx, "shape": list(z.shape),
            "missing_fraction": float(np.isnan(z).mean())}


def output_pitch(ref: dict, grid: int, mode: str) -> float:
    """Pitch of the generated grid: 'field' spans the scan's shorter side, 'native' keeps the scan pitch."""
    if mode == "native":
        return ref["dx_um"]
    if mode == "field":
        return ref["dx_um"] * min(ref["shape"]) / grid
    raise ValueError(mode)
