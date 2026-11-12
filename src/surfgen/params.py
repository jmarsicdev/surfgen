"""ISO 25178-2 areal parameters on a levelled, S-filtered height map.

Heights in micrometres, pitch in micrometres. NOT yet validated against the
ISO 25178-71 softgauges (order-of-work step 1); the feature family in particular
uses a simplified segmentation (h-maxima pruning at 5 % of Sz, edge motifs kept).
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage
from skimage.morphology import h_maxima
from skimage.segmentation import find_boundaries, watershed

FAMILIES = {
    "height": ["Sa", "Sq", "Ssk", "Sku", "Sp", "Sv", "Sz"],
    "spatial": ["Sal", "Str", "Std"],
    "hybrid": ["Sdq", "Sdr"],
    "functional": ["Sk", "Spk", "Svk", "Smr1", "Smr2", "Vmp", "Vmc", "Vvc", "Vvv"],
    "feature": ["Spd", "Spc", "S10z", "Sda", "Sha", "Sdv", "Shv"],
}
LEVELS = list(FAMILIES)

INFO = {  # unit, one-line definition used in the prompt
    "Sa": ("µm", "arithmetic mean height"),
    "Sq": ("µm", "root mean square height"),
    "Ssk": ("", "skewness of the height distribution"),
    "Sku": ("", "kurtosis of the height distribution"),
    "Sp": ("µm", "maximum peak height above the mean plane"),
    "Sv": ("µm", "maximum pit depth below the mean plane"),
    "Sz": ("µm", "maximum height, Sp + Sv"),
    "Sal": ("µm", "autocorrelation length: shortest lag at which the autocorrelation falls to 0.2"),
    "Str": ("", "texture aspect ratio: shortest / longest 0.2 autocorrelation lag (1 = isotropic)"),
    "Std": ("deg", "texture (lay) direction, measured from the row (x) direction, 0-180"),
    "Sdq": ("", "root mean square gradient"),
    "Sdr": ("%", "developed interfacial area ratio"),
    "Sk": ("µm", "core height from the material ratio curve"),
    "Spk": ("µm", "reduced peak height"),
    "Svk": ("µm", "reduced dale (valley) depth"),
    "Smr1": ("%", "material ratio separating peaks from the core"),
    "Smr2": ("%", "material ratio separating dales from the core"),
    "Vmp": ("µm³/µm²", "peak material volume at material ratio 10 %"),
    "Vmc": ("µm³/µm²", "core material volume between material ratios 10 % and 80 %"),
    "Vvc": ("µm³/µm²", "core void volume between material ratios 10 % and 80 %"),
    "Vvv": ("µm³/µm²", "dale void volume at material ratio 80 %"),
    "Spd": ("1/mm²", "density of significant peaks (watershed, Wolf pruning 5 % of Sz)"),
    "Spc": ("1/mm", "arithmetic mean curvature of significant peaks"),
    "S10z": ("µm", "ten-point height: mean of 5 highest peaks plus mean of 5 deepest pits"),
    "Sda": ("µm²", "mean dale area"),
    "Sha": ("µm²", "mean hill area"),
    "Sdv": ("µm³", "mean dale volume"),
    "Shv": ("µm³", "mean hill volume"),
}

# S-filter nesting index as a multiple of the scan pitch; 0 = none. The supplied scans are
# form-removed only (verified against their raw pairs), so no S- or L-filter is applied.
S_FILTER_PIXELS = 0.0


def prepare(z: np.ndarray, dx: float, s_um: float) -> np.ndarray:
    """F-operation (least-squares plane) then Gaussian S-filter with nesting index s_um.

    The nesting index is physical, so the reference scan and a generated grid at a
    different pitch are filtered to the same bandwidth.
    """
    rows, cols = z.shape
    yy, xx = np.mgrid[0:rows, 0:cols]
    a = np.column_stack([xx.ravel(), yy.ravel(), np.ones(z.size)])
    coef, *_ = np.linalg.lstsq(a, z.ravel(), rcond=None)
    z = z - (a @ coef).reshape(z.shape)
    if s_um > 0:
        # ISO 16610-61 Gaussian with cutoff lambda: sigma = lambda * sqrt(ln2 / 2) / pi
        z = ndimage.gaussian_filter(z, sigma=s_um / dx * np.sqrt(np.log(2) / 2) / np.pi, mode="nearest")
    return z - z.mean()


def _acf(z: np.ndarray) -> np.ndarray:
    n0, n1 = z.shape
    f = np.fft.fft2(z, s=(2 * n0, 2 * n1))
    acf = np.fft.fftshift(np.fft.ifft2(np.abs(f) ** 2).real)
    return acf / acf.max()


def _spatial(z: np.ndarray, dx: float) -> dict:
    acf = _acf(z)
    c0, c1 = acf.shape[0] // 2, acf.shape[1] // 2
    rmax = min(z.shape) - 1
    r = np.arange(0, rmax, 0.25)
    lags = []
    for theta in np.deg2rad(np.arange(0, 180, 1.0)):
        prof = ndimage.map_coordinates(acf, [c0 + r * np.sin(theta), c1 + r * np.cos(theta)], order=1)
        below = np.nonzero(prof <= 0.2)[0]
        if below.size == 0:
            lags.append(rmax)
            continue
        i = below[0]
        lags.append(r[i - 1] + (prof[i - 1] - 0.2) / (prof[i - 1] - prof[i]) * 0.25 if i else 0.0)
    lags = np.array(lags)
    # lay direction = direction of slowest autocorrelation decay
    return {"Sal": lags.min() * dx, "Str": lags.min() / lags.max(), "Std": float(np.argmax(lags))}


def _functional(z: np.ndarray) -> dict:
    h = np.sort(z.ravel())[::-1]
    n = h.size
    mr = (np.arange(n) + 0.5) / n * 100
    w = int(0.4 * n)
    i = int(np.argmin(h[:n - w] - h[w:]))
    slope = (h[i + w] - h[i]) / (mr[i + w] - mr[i])
    upper = h[i] - slope * mr[i]
    lower = upper + slope * 100
    smr1 = 100 * np.mean(h > upper)
    smr2 = 100 * np.mean(h > lower)
    a1 = 100 * np.sum(np.clip(h - upper, 0, None)) / n
    a2 = 100 * np.sum(np.clip(lower - h, 0, None)) / n
    c10, c80 = np.percentile(h, 90), np.percentile(h, 20)
    vmp = np.mean(np.clip(z - c10, 0, None))
    vvv = np.mean(np.clip(c80 - z, 0, None))
    return {"Sk": upper - lower, "Spk": 2 * a1 / smr1 if smr1 > 0 else 0.0,
            "Svk": 2 * a2 / (100 - smr2) if smr2 < 100 else 0.0, "Smr1": smr1, "Smr2": smr2,
            "Vmp": vmp, "Vmc": np.mean(np.clip(z - c80, 0, None)) - vmp,
            "Vvc": np.mean(np.clip(c10 - z, 0, None)) - vvv, "Vvv": vvv}


def _motifs(z: np.ndarray, prune: float):
    """Hills of z: peak heights, peak positions, areas (px), volumes (µm·px)."""
    markers, n = ndimage.label(h_maxima(z, prune))
    if n == 0:
        return np.array([]), [], np.array([]), np.array([])
    lab = watershed(-z, markers)
    idx = np.arange(1, n + 1)
    peaks = ndimage.maximum(z, lab, idx)
    pos = ndimage.maximum_position(z, lab, idx)
    areas = ndimage.sum(np.ones_like(z), lab, idx)
    edge = find_boundaries(lab, mode="inner")
    saddle = np.atleast_1d(ndimage.maximum(np.where(edge, z, -np.inf), lab, idx))
    saddle = np.where(np.isfinite(saddle), saddle, np.atleast_1d(ndimage.minimum(z, lab, idx)))
    vols = ndimage.sum(np.clip(z - saddle[lab - 1], 0, None), lab, idx)
    return np.atleast_1d(peaks), pos, np.atleast_1d(areas), np.atleast_1d(vols)


def _feature(z: np.ndarray, dx: float, sz: float) -> dict:
    prune = 0.05 * sz
    hp, hpos, ha, hv = _motifs(z, prune)
    dp, _, da, dv = _motifs(-z, prune)
    area_mm2 = z.size * dx * dx * 1e-6
    lap = ndimage.laplace(z, mode="nearest") / dx ** 2
    curv = [-0.5 * lap[p] for p in hpos]
    top = lambda v: float(np.mean(np.sort(v)[::-1][:5])) if len(v) else 0.0
    mean = lambda v: float(np.mean(v)) if len(v) else 0.0
    return {"Spd": len(hp) / area_mm2, "Spc": mean(curv) * 1e3, "S10z": top(hp) + top(dp),
            "Sda": mean(da) * dx ** 2, "Sha": mean(ha) * dx ** 2,
            "Sdv": mean(dv) * dx ** 2, "Shv": mean(hv) * dx ** 2}


def compute(z: np.ndarray, dx: float) -> dict[str, float]:
    """Full parameter vector for a prepared (levelled, filtered, zero-mean) surface."""
    sq = float(np.sqrt(np.mean(z ** 2)))
    p = {"Sa": float(np.mean(np.abs(z))), "Sq": sq,
         "Ssk": float(np.mean(z ** 3) / sq ** 3) if sq else 0.0,
         "Sku": float(np.mean(z ** 4) / sq ** 4) if sq else 0.0,
         "Sp": float(z.max()), "Sv": float(-z.min()), "Sz": float(z.max() - z.min())}
    if sq == 0:
        return p | {k: float("nan") for fam in LEVELS[1:] for k in FAMILIES[fam]}
    p |= _spatial(z, dx)
    gy, gx = np.gradient(z, dx)
    p |= {"Sdq": float(np.sqrt(np.mean(gx ** 2 + gy ** 2))),
          "Sdr": float(100 * np.mean(np.sqrt(1 + gx ** 2 + gy ** 2) - 1))}
    p |= _functional(z)
    p |= _feature(z, dx, p["Sz"])
    return {k: float(v) for k, v in p.items()}


def radial_psd(z: np.ndarray, dx: float) -> tuple[np.ndarray, np.ndarray]:
    """Radially averaged areal PSD in physical units: (frequency 1/µm, density µm⁴)."""
    n0, n1 = z.shape
    psd = np.abs(np.fft.fft2(z)) ** 2 * dx * dx / (n0 * n1)
    f = np.hypot(*np.meshgrid(np.fft.fftfreq(n0, dx), np.fft.fftfreq(n1, dx), indexing="ij"))
    df = 1.0 / (min(n0, n1) * dx)
    k = np.rint(f / df).astype(int).ravel()
    out = np.bincount(k, psd.ravel()) / np.maximum(np.bincount(k), 1)
    top = min(n0, n1) // 2
    return np.arange(1, top) * df, out[1:top]
