"""Stage 2 — terrain engine (numpy/scipy/skimage; no external binary).

From cache/<aoi>/dem.tif derive, on the working grid:
  slope.tif   — slope in degrees
  aspect.tif  — aspect in degrees (0=N, 90=E)
  tpi.tif     — topographic position (dem - focal mean); + ridge / - valley
  wet.tif     — wetness proxy 0..1 (low slope AND valley) → bog/wallow/flat flats
  funnel.tif  — saddle/pass strength 0..1 (Hessian eigenvalues of opposite sign)
                → Charles Dorris "passe naturel ou entonnoir"
  coolaspect.tif — 0..1 north-facing (thermal-refuge input)

These feed the HSM (habitat), the funnel/pass features, and thermal refuges.
"""
from __future__ import annotations

from .config import Context, cache_dir
from . import rasterio_utils as ru


def run(ctx: Context) -> None:
    import numpy as np
    from scipy.ndimage import gaussian_filter, uniform_filter
    from skimage.feature import hessian_matrix, hessian_matrix_eigvals

    aoi = ctx.aoi.name
    dem_path = cache_dir(aoi) / "dem.tif"
    if not dem_path.exists():
        raise FileNotFoundError("dem.tif — run acquire first")
    tdir = cache_dir(aoi) / "terrain"
    tdir.mkdir(parents=True, exist_ok=True)

    dem, prof = ru.read(dem_path)
    res = abs(prof["transform"].a)  # metres/pixel
    mask = np.isfinite(dem)
    demf = dem.copy()
    demf[~mask] = np.nanmean(dem)
    demf = gaussian_filter(demf, sigma=1.0)

    # --- slope & aspect (gradient in metres) ---
    dzdy, dzdx = np.gradient(demf, res, res)
    slope = np.degrees(np.arctan(np.hypot(dzdx, dzdy)))
    aspect = (np.degrees(np.arctan2(dzdy, -dzdx)) + 360) % 360

    # --- TPI: elevation minus local mean (~500 m window) ---
    win = max(3, int(round(500 / res)) | 1)
    tpi = demf - uniform_filter(demf, size=win)

    # --- wetness proxy: valley bottoms & flats (low slope AND low TPI) ---
    wet = ru.normalize(-tpi) * ru.normalize(slope, invert=True)

    # --- funnels / passes: Hessian eigenvalues of opposite sign = saddle ---
    Hxx, Hxy, Hyy = hessian_matrix(demf, sigma=max(1.0, 60.0 / res), order="rc",
                                   use_gaussian_derivatives=False)
    l1, l2 = hessian_matrix_eigvals([Hxx, Hxy, Hyy])
    saddle = np.where(l1 * l2 < 0, -(l1 * l2), 0.0)  # opposite signs -> pass
    funnel = ru.normalize(saddle) * ru.normalize(slope, invert=True)

    # --- cool (north-facing) aspect 0..1 for thermal refuge ---
    cool = (np.cos(np.radians(aspect)) + 1) / 2  # 1 at N(0/360), 0 at S(180)

    for name, arr in [
        ("slope", slope), ("aspect", aspect), ("tpi", tpi),
        ("wet", wet), ("funnel", funnel), ("coolaspect", cool),
    ]:
        a = arr.copy()
        a[~mask] = np.nan
        ru.write(tdir / f"{name}.tif", a, prof)
