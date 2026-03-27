#!/usr/bin/env python3
"""
Export Google Earth Engine raster assets (e.g. Biodiversity Intactness Index, BII)
as compressed, size-optimized GeoTIFFs suitable for upload to an online map
platform with an upload limit (e.g. ~900 MB).

Designed to:
- Demonstrate on the Biodiversity Intactness Index (BII) global dataset.
- Be reusable for other single-band GEE raster assets.

Source for BII description:
See `https://gee-community-catalog.org/projects/bii/`.

Size reduction strategy (in this order):
1. Compression: cloud-optimized GeoTIFF (tiled, DEFLATE).
2. Data type change: e.g. 0–1 float -> 0–100 integer (0.98765 -> 99).
3. Resolution resampling: only if needed (100 m -> 500 m or 1000 m).

Notes and constraints:
- Always asks for confirmation before starting any export task, so no data
  is generated for download without explicit approval.
- Defaults to:
    * Global export.
    * Most recent year available (for time-series ImageCollections).
    * Native resolution (100 m) when reasonable, but warns if this is
      likely to exceed the ~900 MB upload target.
    * Data scaled from 0–1 to 0–100 (uint8), suitable for BII-like indices.
"""

import argparse
import datetime
import os
import sys
import textwrap
from typing import Optional, Tuple

import ee


# Default Google account to use for Earth Engine (avoids using wrong account when
# multiple are logged in). Override with --expected-account if needed.
DEFAULT_EXPECTED_ACCOUNT = "geoprocessing.cwyc@gmail.com"

# Default GCP project for Earth Engine (numeric ID for biodiversity-intactness-index).
# Use this so the script uses the correct project when multiple exist.
# Override with --project if needed (can be project ID string or project number).
DEFAULT_GEE_PROJECT = "1028186117800"


def _get_gee_credentials_path() -> str:
    """Return the path where Earth Engine stores credentials (platform-specific)."""
    return os.path.join(os.path.expanduser("~"), ".config", "earthengine", "credentials")


def clear_gee_credentials() -> bool:
    """
    Remove cached Earth Engine credentials so the next auth will show the
    Google login page and let the user choose the account. Returns True if
    a file was removed, False otherwise.
    """
    path = _get_gee_credentials_path()
    if os.path.isfile(path):
        try:
            os.remove(path)
            return True
        except OSError:
            return False
    return False


# ---------------------------------------------------------------------------
# Earth Engine initialization
# ---------------------------------------------------------------------------

def init_gee(
    project_id: Optional[str] = None,
    expected_account: Optional[str] = None,
) -> None:
    """
    Initialize the Earth Engine client.

    If project_id is set (e.g. your GCP project registered with GEE), Earth
    Engine will run in that project's context, which can resolve access or
    quota issues when the project is already registered in GEE.

    If expected_account is set and authentication is needed, the user is
    reminded to sign in with that account so the wrong Google account is not
    used when multiple are logged in.
    """
    try:
        if project_id:
            ee.Initialize(project=project_id)
        else:
            ee.Initialize()
    except Exception:
        if expected_account:
            print(
                textwrap.dedent(
                    f"""
                    >>> Earth Engine sign-in will open in your browser.
                    >>> IMPORTANT: Use the account  {expected_account}
                    >>> If multiple Google accounts are logged in, choose that one
                    >>> (or use a private/incognito window with only that account).
                    """
                ).strip()
            )
        ee.Authenticate()
        if project_id:
            ee.Initialize(project=project_id)
        else:
            ee.Initialize()


def run_login_flow(
    expected_account: str,
    project_id: Optional[str] = None,
) -> None:
    """
    Force the Google Earth Engine login page so the user can choose the
    correct account in the browser. Clears any cached credentials first,
    then runs ee.Authenticate() so a new OAuth flow is started and the
    user can select the right Google account (e.g. when multiple are
    logged in).
    """
    removed = clear_gee_credentials()
    if removed:
        print("Cleared existing Earth Engine credentials (so you can choose the account again).")
    print(
        textwrap.dedent(
            f"""
            A browser window or login URL will appear. Use it to sign in to Earth Engine.

            >>> IMPORTANT: Sign in with  {expected_account}
            >>> If multiple Google accounts are listed, choose that one.
            >>> (Using a private/incognito window with only that account can help.)

            After you complete sign-in and paste any code back here, this script
            will save the new credentials and exit. Run the script again without
            --login to perform the export.
            """
        ).strip()
    )
    # Force new OAuth flow; some API versions support force=True
    try:
        ee.Authenticate(force=True)
    except TypeError:
        ee.Authenticate()
    if project_id:
        ee.Initialize(project=project_id)
    else:
        ee.Initialize()
    print(
        "\nLogin successful. Run the script again without --login to perform the export."
    )


# ---------------------------------------------------------------------------
# Asset loading and temporal handling
# ---------------------------------------------------------------------------

def get_latest_year_from_collection(ic: ee.ImageCollection) -> int:
    """
    Determine the most recent year present in an ImageCollection
    using the 'system:time_start' property.
    """
    max_time = ic.aggregate_max("system:time_start").getInfo()
    # max_time is milliseconds since epoch
    dt = datetime.datetime.utcfromtimestamp(max_time / 1000.0)
    return dt.year


def load_image_from_asset(
    asset_id: str,
    band: Optional[str] = None,
    year: Optional[int] = None,
    multi_year_mean: bool = False,
    auto_latest: bool = True,
) -> ee.Image:
    """
    Load an ee.Image from a GEE asset.

    Works for:
    - ImageCollection assets (using year, multi-year mean, or latest year).
    - Single Image assets (year parameters are ignored).

    Parameters
    ----------
    asset_id : str
        EE asset ID (e.g. 'projects/ebx-data/assets/earthblox/IO/BIOINTACT').
    band : str or None
        Band name to select. If None, the first band is used.
    year : int or None
        Year to filter on for time-series collections.
    multi_year_mean : bool
        If True and year is None, use the mean of the entire collection.
    auto_latest : bool
        If True and year is None and multi_year_mean is False, use the most
        recent year in the collection.

    Returns
    -------
    ee.Image
    """
    # Try treating as an ImageCollection
    as_ic = ee.ImageCollection(asset_id)

    try:
        size = as_ic.size().getInfo()
    except Exception:
        size = 0

    if size and size > 0:
        # Asset behaves as an ImageCollection
        if year is not None:
            start = f"{year}-01-01"
            end = f"{year}-12-31"
            img = as_ic.filterDate(start, end).mean()
        elif multi_year_mean:
            img = as_ic.mean()
        elif auto_latest:
            latest_year = get_latest_year_from_collection(as_ic)
            start = f"{latest_year}-01-01"
            end = f"{latest_year}-12-31"
            img = as_ic.filterDate(start, end).mean()
        else:
            img = as_ic.mean()
    else:
        # Fallback: treat asset as a single Image
        img = ee.Image(asset_id)

    band_names = img.bandNames()
    band_list = band_names.getInfo()

    if band is not None:
        if band not in band_list:
            raise ValueError(
                f"Requested band '{band}' not found in asset. "
                f"Available bands: {band_list}"
            )
        img = img.select(band)
    else:
        # Use the first band by default
        img = img.select(0)

    return img


# ---------------------------------------------------------------------------
# Data type scaling and metadata
# ---------------------------------------------------------------------------

def apply_dtype_scaling(
    img: ee.Image,
    scale_factor: int = 100,
    clamp_min: int = 0,
    clamp_max: int = 100,
) -> ee.Image:
    """
    Convert (approximate) 0–1 float values to integer 0–100 (or similar)
    to reduce file size. Example: 0.98765 -> 99 (scale_factor=100).

    Parameters
    ----------
    img : ee.Image
        Input image, typically with values ~0–1 (e.g. BII index).
    scale_factor : int
        Multiplicative factor before rounding and casting.
    clamp_min : int
        Minimum allowed value after scaling.
    clamp_max : int
        Maximum allowed value after scaling.
    """
    scaled = img.multiply(scale_factor)
    scaled = scaled.round()
    scaled = scaled.clamp(clamp_min, clamp_max)
    scaled = scaled.toUint8()
    return scaled


def build_export_image(
    asset_id: str,
    band: Optional[str],
    year: Optional[int],
    multi_year_mean: bool,
    auto_latest: bool,
    scale_factor: int,
    resample_method: str = "bilinear",
    enable_int_scaling: bool = True,
) -> ee.Image:
    """
    Build the final ee.Image to export, applying:
    - Asset loading (ImageCollection or Image).
    - Optional resample hint.
    - Optional data-type scaling to 8-bit ints.
    """
    img = load_image_from_asset(
        asset_id=asset_id,
        band=band,
        year=year,
        multi_year_mean=multi_year_mean,
        auto_latest=auto_latest,
    )

    img = img.resample(resample_method)

    if enable_int_scaling:
        img = apply_dtype_scaling(img, scale_factor=scale_factor)
        img = img.set({
            "processing_steps": (
                f"scale_to_0_{scale_factor}_uint8, resample_hint_{resample_method}"
            )
        })
    else:
        img = img.set({
            "processing_steps": f"no_int_scaling, resample_hint_{resample_method}"
        })

    return img


# ---------------------------------------------------------------------------
# Size estimation and user confirmation
# ---------------------------------------------------------------------------

# Export region used (same as get_global_region_no_poles) for size estimate.
_EXPORT_LAT_MIN = -85.0
_EXPORT_LAT_MAX = 85.0


def estimate_export_size_mb(
    scale_m: float,
    bytes_per_pixel: int = 1,
    lat_min: float = _EXPORT_LAT_MIN,
    lat_max: float = _EXPORT_LAT_MAX,
) -> Tuple[float, float]:
    """
    Estimate export size for the actual global region (rectangle -85 to 85 lat).

    Returns
    -------
    pixels : float
        Estimated number of pixels.
    size_mb : float
        Estimated uncompressed size in megabytes.
    """
    # Approximate m per degree at mid-latitude (45°): ~111320 m/deg
    m_per_deg = 111320.0
    lon_span_deg = 360.0
    lat_span_deg = lat_max - lat_min
    # Area in m² (approximate for a lat-lon rectangle)
    area_m2 = (lon_span_deg * m_per_deg) * (lat_span_deg * m_per_deg)
    pixel_area = scale_m * scale_m
    pixels = area_m2 / pixel_area
    size_bytes = pixels * bytes_per_pixel
    size_mb = size_bytes / (1024.0 * 1024.0)
    return pixels, size_mb


def estimate_pixels_and_size(
    scale_m: float,
    global_land_fraction: float = 0.29,
    bytes_per_pixel: int = 1,
) -> Tuple[float, float]:
    """
    Rough estimate of uncompressed raster size for a global land-only export.
    """
    earth_area_m2 = 510e12  # 510 million km²
    land_area_m2 = earth_area_m2 * global_land_fraction
    pixel_area = scale_m * scale_m
    pixels = land_area_m2 / pixel_area
    size_bytes = pixels * bytes_per_pixel
    size_mb = size_bytes / (1024.0 * 1024.0)
    return pixels, size_mb


def print_size_estimate(
    scale: float,
    max_upload_mb: float,
    enable_int_scaling: bool,
) -> float:
    """
    Print a rough estimate of raster size and return the estimated size in MB
    for the actual export region (global -85 to 85).
    """
    bytes_per_pixel = 1 if enable_int_scaling else 4  # very rough for float
    pixels, size_mb = estimate_export_size_mb(scale, bytes_per_pixel=bytes_per_pixel)

    print(
        textwrap.dedent(
            f"""
            === Export size estimate (region: lat {_EXPORT_LAT_MIN}° to {_EXPORT_LAT_MAX}°) ===
            Pixel scale: {scale} m
            Estimated pixels: ~{pixels:,.0f}
            Estimated uncompressed size (1 band): ~{size_mb:,.1f} MB

            NOTE: The actual downloaded GeoTIFF may be smaller if the export
            is compressed. If you need to stay under {max_upload_mb} MB,
            consider increasing --scale (e.g. 500 or 1000).
            """
        ).strip()
    )
    return size_mb


def confirm_proceed() -> bool:
    """
    Ask user whether to proceed with starting the GEE export task.
    This ensures we always ask before any data export is started.
    """
    while True:
        answer = input(
            "\nDo you want to start the Earth Engine export now? [y/N]: "
        ).strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no", ""):
            return False
        print("Please answer 'y' or 'n'.")


# ---------------------------------------------------------------------------
# Export region (avoid poles to prevent EPSG:4326 planar transform errors)
# ---------------------------------------------------------------------------

# Use longitude slightly inside the date line so the export is not degenerate
# (exactly -180/180 can yield X: 1 or wrong extent in some exports).
_GLOBAL_LON_WEST = -179.99
_GLOBAL_LON_EAST = 179.99


def get_global_region_no_poles(
    lat_max: float = 85.0,
    lat_min: float = -85.0,
) -> ee.Geometry.Rectangle:
    """
    Return a global rectangle that avoids the poles and uses longitude
    slightly inside the date line (-179.99 to 179.99) so the export has
    full horizontal extent (avoids X: 1 degenerate output).
    """
    return ee.Geometry.Rectangle([_GLOBAL_LON_WEST, lat_min, _GLOBAL_LON_EAST, lat_max])


def get_longitude_band_regions(
    n_bands: int,
    lat_min: float = -85.0,
    lat_max: float = 85.0,
) -> list:
    """
    Split global extent into n_bands longitude bands. Returns a list of
    (west, south, east, north) tuples for each band, so each export has
    a normal aspect ratio and avoids the thin-strip issue.
    """
    assert n_bands >= 1
    lon_span = _GLOBAL_LON_EAST - _GLOBAL_LON_WEST  # 359.98
    band_width = lon_span / n_bands
    bands = []
    for i in range(n_bands):
        west = _GLOBAL_LON_WEST + i * band_width
        east = _GLOBAL_LON_WEST + (i + 1) * band_width
        bands.append((west, lat_min, east, lat_max))
    return bands


# Expected global extent (lon, lat) for coverage check. Match get_global_region_no_poles.
_EXPECTED_WEST = -180.0
_EXPECTED_EAST = 180.0
_EXPECTED_SOUTH = -85.0
_EXPECTED_NORTH = 85.0
_COVERAGE_TOLERANCE_DEG = 1.0


def _bounds_from_geometry(geom: ee.Geometry) -> Tuple[float, float, float, float]:
    """Get (west, south, east, north) from an ee.Geometry via getInfo()."""
    info = geom.bounds().getInfo()
    if not info or "coordinates" not in info:
        raise ValueError("Could not get bounds from geometry")
    coords = info["coordinates"][0]
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    w, s, e, n = (min(lons), min(lats), max(lons), max(lats))
    # Earth Engine can return bounds that cross the date line (e.g. west=180, east=-180)
    # or otherwise indicate full longitude span. Normalize to -180..180 for the check.
    if w > e:
        w, e = -180.0, 180.0
    elif (abs(w - 180) <= 2 and abs(e + 180) <= 2) or (abs(w + 180) <= 2 and abs(e - 180) <= 2):
        w, e = -180.0, 180.0
    elif abs(w - 180) < 1 and abs(e - 180) < 1:
        w, e = -180.0, 180.0
    elif abs(w + 180) < 1 and abs(e + 180) < 1:
        w, e = -180.0, 180.0
    # EE sometimes returns west=180 for a global rectangle; treat as full span.
    elif w >= 179 or e <= -179:
        w, e = -180.0, 180.0
    return (w, s, e, n)


def check_global_coverage(
    region: ee.Geometry,
    image: ee.Image,
    tolerance_deg: float = _COVERAGE_TOLERANCE_DEG,
) -> Tuple[bool, str]:
    """
    Verify that the export region and image footprint provide global coverage
    (approx. -180, -85, 180, 85) before exporting. Returns (True, msg) if ok,
    (False, msg) if coverage is not global.
    """
    try:
        w, s, e, n = _bounds_from_geometry(region)
        if w > _EXPECTED_WEST + tolerance_deg:
            return (False, f"Export region west ({w}) is not global (expected ~{_EXPECTED_WEST}).")
        if e < _EXPECTED_EAST - tolerance_deg:
            return (False, f"Export region east ({e}) is not global (expected ~{_EXPECTED_EAST}).")
        if s > _EXPECTED_SOUTH + tolerance_deg:
            return (False, f"Export region south ({s}) is not global (expected ~{_EXPECTED_SOUTH}).")
        if n < _EXPECTED_NORTH - tolerance_deg:
            return (False, f"Export region north ({n}) is not global (expected ~{_EXPECTED_NORTH}).")
    except Exception as exc:
        return (False, f"Could not get export region bounds: {exc}")

    try:
        img_footprint = image.geometry()
        iw, isouth, ie, inorth = _bounds_from_geometry(img_footprint)
        if iw > _EXPECTED_WEST + tolerance_deg or ie < _EXPECTED_EAST - tolerance_deg:
            return (
                False,
                f"Image footprint (lon {iw:.2f} to {ie:.2f}) does not cover global extent "
                f"({_EXPECTED_WEST} to {_EXPECTED_EAST}). Export may have missing or wrong coverage.",
            )
        if isouth > _EXPECTED_SOUTH + tolerance_deg or inorth < _EXPECTED_NORTH - tolerance_deg:
            return (
                False,
                f"Image footprint (lat {isouth:.2f} to {inorth:.2f}) does not cover global extent "
                f"({_EXPECTED_SOUTH} to {_EXPECTED_NORTH}). Export may have missing or wrong coverage.",
            )
    except Exception as exc:
        return (False, f"Could not get image footprint bounds: {exc}")

    return (True, f"Global coverage OK (region and image cover ~{_EXPECTED_WEST},{_EXPECTED_SOUTH} to {_EXPECTED_EAST},{_EXPECTED_NORTH}).")


# ---------------------------------------------------------------------------
# Export task creation
# ---------------------------------------------------------------------------

def create_export_task(
    img: ee.Image,
    description: str,
    scale: float,
    region: Optional[ee.Geometry],
    destination: str,
    drive_folder: Optional[str],
    gcs_bucket: Optional[str],
    max_pixels: float = 1e13,
) -> ee.batch.Task:
    """
    Create an Earth Engine export task with compression and tiling settings.

    Parameters
    ----------
    img : ee.Image
    description : str
        Task description.
    scale : float
        Pixel size in meters.
    region : ee.Geometry or None
        Export region. If None, uses the image footprint (global by default).
    destination : str
        'DRIVE' or 'CLOUD_STORAGE'.
    drive_folder : str or None
        Google Drive folder name if destination is DRIVE.
    gcs_bucket : str or None
        GCS bucket name if destination is CLOUD_STORAGE.
    """
    # GeoTIFF options: use only options supported by the EE Python API.
    # (cloudOptimized is supported; tileSize/compression/blockSize are not in this client.)
    format_options = {
        "cloudOptimized": True,
    }

    # Explicit CRS so the export has correct global dimensions (avoids X: 24 strip).
    common_kwargs = dict(
        image=img,
        description=description,
        scale=scale,
        maxPixels=max_pixels,
        fileFormat="GeoTIFF",
        formatOptions=format_options,
        crs="EPSG:4326",
    )

    if region is not None:
        common_kwargs["region"] = region

    dest = destination.upper()
    if dest == "DRIVE":
        if drive_folder:
            common_kwargs["folder"] = drive_folder
        task = ee.batch.Export.image.toDrive(**common_kwargs)
    elif dest == "CLOUD_STORAGE":
        if not gcs_bucket:
            raise ValueError(
                "gcs_bucket must be provided when destination='CLOUD_STORAGE'."
            )
        common_kwargs["bucket"] = gcs_bucket
        task = ee.batch.Export.image.toCloudStorage(**common_kwargs)
    else:
        raise ValueError("destination must be 'DRIVE' or 'CLOUD_STORAGE'.")

    return task


# ---------------------------------------------------------------------------
# Main CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Export a Google Earth Engine raster asset (e.g. BII) as a "
            "compressed, size-optimized GeoTIFF suitable for upload."
        )
    )

    parser.add_argument(
        "--asset",
        type=str,
        default="projects/ebx-data/assets/earthblox/IO/BIOINTACT",
        help=(
            "Earth Engine asset ID. Default is the Biodiversity Intactness "
            "Index (BII) ImageCollection from the community catalog."
        ),
    )
    parser.add_argument(
        "--project",
        type=str,
        default=DEFAULT_GEE_PROJECT,
        help=(
            "Google Cloud project for Earth Engine: project ID (e.g. "
            "biodiversity-intactness-index) or project number (e.g. 1028186117800). "
            "Default: 1028186117800 (biodiversity-intactness-index)."
        ),
    )
    parser.add_argument(
        "--expected-account",
        type=str,
        default=DEFAULT_EXPECTED_ACCOUNT,
        help=(
            "Google account to use for Earth Engine (e.g. geoprocessing.cwyc@gmail.com). "
            "When authentication runs, you will be reminded to sign in with this account. "
            "Use this to avoid using the wrong account when multiple are logged in."
        ),
    )
    parser.add_argument(
        "--login",
        action="store_true",
        help=(
            "Only run the Earth Engine login flow: clear cached credentials and open "
            "the Google sign-in page so you can select the right account (e.g. when "
            "multiple accounts are logged in). After signing in, run the script again "
            "without --login to perform the export."
        ),
    )
    parser.add_argument(
        "--band",
        type=str,
        default=None,
        help="Band name to export. If omitted, the first band is used.",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        help=(
            "Year to export (for time-series collections). "
            "If omitted, the script uses the most recent available year."
        ),
    )
    parser.add_argument(
        "--multi-year-mean",
        action="store_true",
        help=(
            "Use the mean of the entire ImageCollection instead of a single "
            "year (ignored if --year is provided)."
        ),
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=100.0,
        help=(
            "Pixel size in meters. Default is 100 m (native for BII). "
            "Increase this to 500 or 1000 if needed to reduce file size."
        ),
    )
    parser.add_argument(
        "--data-format",
        type=str,
        default="float",
        choices=["float", "uint8"],
        help=(
            "Export data type: 'float' (0–1, original) or 'uint8' (0–100 integer). "
            "Default: float. Use uint8 to reduce file size; use float when compression "
            "already keeps the file under your limit and you want highest value precision."
        ),
    )
    parser.add_argument(
        "--scale-factor",
        type=int,
        default=100,
        help=(
            "When --data-format uint8: factor for 0–1 -> 0–N integer (e.g. 100 -> 0–100). "
            "Ignored when --data-format float. Default: 100."
        ),
    )
    parser.add_argument(
        "--no-int-scaling",
        action="store_true",
        help=(
            "Deprecated: same as --data-format float. Exports original 0–1 float."
        ),
    )
    parser.add_argument(
        "--destination",
        type=str,
        default="DRIVE",
        choices=["DRIVE", "CLOUD_STORAGE", "drive", "cloud_storage"],
        help="Export destination: Google DRIVE or CLOUD_STORAGE. Default: DRIVE.",
    )
    parser.add_argument(
        "--drive-folder",
        type=str,
        default="GEE_exports",
        help="Google Drive folder to place the exported file (if destination=DRIVE).",
    )
    parser.add_argument(
        "--gcs-bucket",
        type=str,
        default=None,
        help="Google Cloud Storage bucket name (if destination=CLOUD_STORAGE).",
    )
    parser.add_argument(
        "--max-upload-mb",
        type=float,
        default=900.0,
        help="Maximum target upload size in MB (for guidance only).",
    )
    parser.add_argument(
        "--skip-global-check",
        action="store_true",
        help=(
            "Skip the pre-export check that region and image have global coverage. "
            "Use only if you intend a non-global export or the check fails incorrectly."
        ),
    )
    parser.add_argument(
        "--longitude-bands",
        type=int,
        default=1,
        metavar="N",
        help=(
            "Split global export into N longitude bands (default: 1). Use 6 or 12 when "
            "a single export gives a thin strip (X: 24). Each band is exported separately; "
            "download all .tif files and run mosaic_geotiff_tiles.py to get one global raster."
        ),
    )

    args = parser.parse_args()

    if args.login:
        run_login_flow(
            expected_account=args.expected_account,
            project_id=args.project,
        )
        sys.exit(0)

    # Default: float (no conversion). Use --data-format uint8 to convert to 0–100.
    enable_int_scaling = (args.data_format == "uint8") and not args.no_int_scaling

    print(
        textwrap.dedent(
            """
            ------------------------------------------------------------
            GEE raster export (global, size-optimized)
            ------------------------------------------------------------
            Size reduction order:
            1) Compression: cloud-optimized GeoTIFF (when applied by GEE).
            2) Data type: --data-format float (default) or uint8 (0–100).
            3) Resolution: --scale in meters (e.g. 100, 500, 1000).
            """
        )
    )
    print(
        f"Using Google account for GEE: {args.expected_account} "
        "(if sign-in opens, choose this account)"
    )

    year_label = (
        str(args.year)
        if args.year is not None
        else "AUTO (most recent available year for collections)"
    )

    print(f"Asset ID: {args.asset}")
    print(f"Band: {args.band if args.band else 'first band'}")
    print(f"Year selection: {year_label}")
    print(f"Pixel scale (resolution): {args.scale} m")
    print(
        f"Data format: {args.data_format} "
        f"{'(0–1 float, no conversion)' if not enable_int_scaling else f'(0–{args.scale_factor} uint8)'}"
    )
    print(f"Expected Google account (for GEE): {args.expected_account}")
    print(f"GCP project (for GEE): {args.project}")
    print(f"Export destination: {args.destination.upper()}")
    print(f"Max upload target (guidance): {args.max_upload_mb} MB")

    estimated_size_mb = print_size_estimate(
        scale=args.scale,
        max_upload_mb=args.max_upload_mb,
        enable_int_scaling=enable_int_scaling,
    )

    print(
        f"\n>>> Estimated export size: ~{estimated_size_mb:,.1f} MB "
        "(uncompressed; actual file may be smaller) <<<\n"
    )

    if not confirm_proceed():
        print("User chose not to start the export. Exiting without exporting.")
        return

    init_gee(
        project_id=args.project,
        expected_account=args.expected_account,
    )

    img = build_export_image(
        asset_id=args.asset,
        band=args.band,
        year=args.year,
        multi_year_mean=args.multi_year_mean,
        auto_latest=True,
        scale_factor=args.scale_factor,
        resample_method="bilinear",
        enable_int_scaling=enable_int_scaling,
    )

    n_bands = max(1, int(args.longitude_bands))
    band_regions = get_longitude_band_regions(n_bands) if n_bands > 1 else None

    img = img.reproject(crs="EPSG:4326", scale=args.scale)

    if n_bands == 1:
        region = get_global_region_no_poles()
        img_clip = img.clip(region)
        if not args.skip_global_check:
            ok, msg = check_global_coverage(region, img_clip)
            if not ok:
                print(
                    f"\n>>> Global coverage check failed: {msg}\n"
                    "Export was not started. Try --longitude-bands 6 to export "
                    "in bands and mosaic for global coverage.",
                    file=sys.stderr,
                )
                sys.exit(1)
            print(f">>> {msg}")
        description = (
            f"gee_export_{args.scale:.0f}m_{'uint8' if enable_int_scaling else 'orig'}"
        )
        task = create_export_task(
            img=img_clip,
            description=description,
            scale=args.scale,
            region=region,
            destination=args.destination,
            drive_folder=args.drive_folder,
            gcs_bucket=args.gcs_bucket,
        )
        task.start()
        print(
            textwrap.dedent(
                f"""
                Export task started: {description}
                - Download from: {args.drive_folder or args.gcs_bucket or 'GEE'}
                - If you get a thin strip, re-run with: --longitude-bands 6
                """
            ).strip()
        )
    else:
        for i, (west, south, east, north) in enumerate(band_regions):
            band_region = ee.Geometry.Rectangle([west, south, east, north])
            img_band = img.clip(band_region)
            description = (
                f"gee_export_{args.scale:.0f}m_{'uint8' if enable_int_scaling else 'orig'}"
                f"_band_{i + 1}_of_{n_bands}"
            )
            task = create_export_task(
                img=img_band,
                description=description,
                scale=args.scale,
                region=band_region,
                destination=args.destination,
                drive_folder=args.drive_folder,
                gcs_bucket=args.gcs_bucket,
            )
            task.start()
            print(f"  Started {description} (lon {west:.1f}° to {east:.1f}°)")
        print(
            textwrap.dedent(
                f"""
                Started {n_bands} export task(s) (longitude bands).

                Download ALL {n_bands} .tif files from: {args.drive_folder or args.gcs_bucket or 'GEE'}
                Then mosaic into one global raster:

                    python mosaic_geotiff_tiles.py GEE_exports ./bii_global.tif

                Monitor: ee.batch.Task.list()
                """
            ).strip()
        )


if __name__ == "__main__":
    main()

