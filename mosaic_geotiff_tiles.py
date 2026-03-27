#!/usr/bin/env python3
"""
Mosaic multiple GeoTIFF tile files (e.g. from a GEE export) into a single GeoTIFF.

Run this locally after downloading tile files from Google Drive (folder GEE_exports).
Give the path to the LOCAL folder where the tiles are saved (e.g. after downloading
GEE_exports from Drive to your computer). By default all .tif files are merged;
use --match to mosaic only files whose name contains a string (e.g. 100m).

Usage:
  python mosaic_geotiff_tiles.py [INPUT_DIR] [output.tif]
  python mosaic_geotiff_tiles.py
  python mosaic_geotiff_tiles.py GEE_exports ./mosaicked_bii.tif
  python mosaic_geotiff_tiles.py GEE_exports ./bii_100m.tif --match 100m

Input folder defaults to GEE_exports (download this folder from Google Drive first).
If the mosaic extent is wrong (e.g. a thin strip at -180), use --bounds -180,-85,180,85
to force global extent (same pixel grid, corrected georeferencing).

Requires:
- rasterio (pip install rasterio)
- tqdm (pip install tqdm)
- GDAL command line tools (gdalbuildvrt, gdal_translate) for the GDAL backend
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import rasterio
    from rasterio.merge import merge
    from rasterio.transform import from_bounds
except ImportError:
    print("This script requires rasterio. Install with: pip install rasterio", file=sys.stderr)
    sys.exit(1)

try:
    from tqdm import tqdm
except ImportError:
    print("This script requires tqdm for the progress bar. Install with: pip install tqdm", file=sys.stderr)
    sys.exit(1)


def _mosaic_one_batch(paths, out_path: Path, bounds_str: str | None = None) -> Path:
    """
    Mosaic a single batch of input files into out_path.
    Optionally apply bounds_str (W,S,E,N) to the output transform.
    """
    src_files = [rasterio.open(p) for p in paths]
    try:
        mosaic, out_transform = merge(src_files)
        height, width = mosaic.shape[1], mosaic.shape[2]
        out_meta = src_files[0].meta.copy()
        out_meta.update({
            "height": height,
            "width": width,
            "transform": out_transform,
            # Lossless compression & tiling for fast subset/resolution access.
            "compress": "DEFLATE",
            "tiled": True,
            "blockxsize": 256,
            "blockysize": 256,
        })

        if bounds_str:
            try:
                w, s, e, n = (float(x.strip()) for x in bounds_str.split(","))
            except (ValueError, AttributeError):
                print(
                    "Error: --bounds must be west,south,east,north (e.g. -180,-85,180,85)",
                    file=sys.stderr,
                )
                sys.exit(1)
            out_meta["transform"] = from_bounds(w, s, e, n, width, height)
            print(f"Output extent set to: {w}, {s}, {e}, {n} (--bounds)")

        with rasterio.open(out_path, "w", **out_meta) as dst:
            dst.write(mosaic)

        print(f"    Wrote {out_path} (~{out_path.stat().st_size/1e6:.1f} MB)")
        return out_path
    finally:
        for s in src_files:
            s.close()


def staged_mosaic(tiles: list[Path], final_output: Path, bounds_str: str | None, batch_size: int) -> None:
    """
    Perform a staged (multi-round) mosaic so we never load too many tiles
    into memory at once. In each round we:

      tiles -> [partial_1, partial_2, ...] -> ... -> final_output

    The final round applies bounds_str (if provided).
    """
    current = [Path(p) for p in tiles]
    work_dir = final_output.parent
    work_dir.mkdir(parents=True, exist_ok=True)

    round_num = 1
    while len(current) > 1:
        print(f"\n=== Mosaic round {round_num}, {len(current)} input file(s) ===")
        batches = [current[i : i + batch_size] for i in range(0, len(current), batch_size)]
        next_paths: list[Path] = []

        # Final round when all remaining inputs fit in a single batch
        is_final_round = len(current) <= batch_size
        for batch_idx, batch in enumerate(tqdm(batches, desc=f"Round {round_num}", unit="batch")):
            print(f"  Batch {batch_idx + 1}/{len(batches)}: {len(batch)} file(s)")
            batch_out = work_dir / f"_mosaic_r{round_num}_b{batch_idx + 1}.tif"
            # Only apply bounds in the very last round and only when there's a single batch.
            apply_bounds = bounds_str if (is_final_round and len(batches) == 1) else None
            out = _mosaic_one_batch(batch, batch_out, bounds_str=apply_bounds)
            next_paths.append(out)

        current = next_paths
        round_num += 1

    # current has exactly one file: rename/move to final_output
    final_tmp = current[0]
    if final_tmp != final_output:
        if final_output.exists():
            final_output.unlink()
        final_tmp.rename(final_output)
    print(f"\nFinal mosaic: {final_output}")


def _ensure_gdal_tools() -> None:
    """Ensure gdalbuildvrt and gdal_translate are available on PATH."""
    missing = []
    for tool in ("gdalbuildvrt", "gdal_translate"):
        if shutil.which(tool) is None:
            missing.append(tool)
    if missing:
        print(
            "Missing required GDAL tools: " + ", ".join(missing) + "\n"
            "Install GDAL (e.g. `conda install -c conda-forge gdal`) so that "
            "gdalbuildvrt and gdal_translate are available on your PATH.",
            file=sys.stderr,
        )
        sys.exit(1)


def gdal_build_cog_from_vrt(
    tiles: list[Path],
    final_output: Path,
    bounds_str: str | None,
    cachemax_mb: int,
    downsample_to_500m: bool,
) -> None:
    """
    Build a VRT over the input tiles and let GDAL translate it into a COG.

    This mirrors the manual steps:
      1) gdalbuildvrt <vrt> <tiles...>
      2) gdal_translate -of COG -co COMPRESS=DEFLATE -co BIGTIFF=YES [opts] <vrt> <out.tif>
    """
    _ensure_gdal_tools()

    tiles = [Path(p) for p in tiles]
    work_dir = final_output.parent
    work_dir.mkdir(parents=True, exist_ok=True)

    vrt_path = work_dir / (final_output.stem + ".vrt")

    print(f"Building VRT {vrt_path} from {len(tiles)} file(s)...")
    build_cmd = ["gdalbuildvrt", str(vrt_path)] + [str(p) for p in tiles]
    subprocess.run(build_cmd, check=True)

    print("Translating VRT to COG...")
    translate_cmd = [
        "gdal_translate",
        "-of",
        "COG",
        "-co",
        "COMPRESS=DEFLATE",
        "-co",
        "BIGTIFF=YES",
    ]

    if downsample_to_500m:
        # Roughly 5x coarser in each dimension -> ~500 m if source is ~100 m.
        translate_cmd += ["-r", "average", "-outsize", "20%", "20%"]

    # Optionally adjust georeferencing if bounds are provided.
    if bounds_str:
        try:
            w, s, e, n = (float(x.strip()) for x in bounds_str.split(","))
        except (ValueError, AttributeError):
            print(
                "Error: --bounds must be west,south,east,north (e.g. -180,-85,180,85)",
                file=sys.stderr,
            )
            sys.exit(1)
        # gdal_translate expects west, north, east, south for -a_ullr
        translate_cmd += ["-a_ullr", str(w), str(n), str(e), str(s)]
        print(f"Output extent (via GDAL -a_ullr) set to: {w}, {s}, {e}, {n}")

    translate_cmd += [str(vrt_path), str(final_output)]

    env = os.environ.copy()
    env["GDAL_CACHEMAX"] = str(cachemax_mb)
    print(f"Using GDAL_CACHEMAX={cachemax_mb} MB")

    subprocess.run(translate_cmd, check=True, env=env)
    print(f"\nFinal COG written to: {final_output}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mosaic all GeoTIFF tiles in a directory into a single GeoTIFF."
    )
    parser.add_argument(
        "input_dir",
        type=str,
        nargs="?",
        default="/Volumes/Kingston/BII",
        metavar="INPUT_DIR",
        help=(
            "Local path to the folder containing the .tif tiles. "
            "Default: /Volumes/Kingston/BII (the 'BII' folder on the Kingston drive). "
            "Override if your tiles are in a different location."
        ),
    )
    parser.add_argument(
        "output",
        type=str,
        nargs="?",
        default=None,
        help="Output GeoTIFF path. Default: <input_dir>/mosaicked.tif",
    )
    parser.add_argument(
        "--suffix",
        type=str,
        default=".tif",
        help="File suffix to match (default: .tif). Use .tif.gz if tiles are gzipped.",
    )
    parser.add_argument(
        "--match",
        type=str,
        default=None,
        metavar="STRING",
        help=(
            "Only mosaic files whose name contains this string (case-insensitive). "
            "E.g. --match 100m to merge only tiles from a 100 m export; "
            "--match 500m for 500 m tiles."
        ),
    )
    parser.add_argument(
        "--bounds",
        type=str,
        default=None,
        metavar="W,S,E,N",
        help=(
            "Force output extent to these bounds (west, south, east, north in degrees). "
            "Use when tile metadata is wrong and the mosaic shows a thin strip. "
            "E.g. --bounds -180,-85,180,85 for global (lat -85 to 85)."
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=4,
        help=(
            "Maximum number of input files to merge in memory at once (default: 4). "
            "Lower this value if you still hit memory limits; increase it cautiously "
            "if your machine has plenty of RAM."
        ),
    )
    parser.add_argument(
        "--backend",
        type=str,
        default="gdal",
        choices=["gdal", "rasterio"],
        help=(
            "Backend to use for mosaicking: 'gdal' (build VRT + COG via gdalbuildvrt/"
            "gdal_translate) or 'rasterio' (Python staged merge). Default: gdal."
        ),
    )
    parser.add_argument(
        "--gdal-cachemax",
        type=int,
        default=512,
        help=(
            "Maximum GDAL cache size in MB when using the gdal backend "
            "(sets GDAL_CACHEMAX, default: 512)."
        ),
    )
    parser.add_argument(
        "--downsample-500m",
        action="store_true",
        help=(
            "When using the gdal backend, downsample the VRT to ~500 m resolution "
            "(approx. 20%% of original width/height) using -r average."
        ),
    )

    args = parser.parse_args()

    input_path = Path(args.input_dir).expanduser().resolve()
    if not input_path.exists():
        print(
            f"Error: path does not exist: {input_path}\n"
            "Use the local path to the folder where the tiles are saved "
            "(e.g. after downloading GEE_exports from Google Drive).",
            file=sys.stderr,
        )
        sys.exit(1)
    if not input_path.is_dir():
        print(
            f"Error: not a directory: {input_path}\n"
            "Give the path to the folder containing the .tif files (e.g. GEE_exports).",
            file=sys.stderr,
        )
        sys.exit(1)

    all_tiles = sorted(input_path.glob(f"*{args.suffix}"))
    if args.match:
        match_lower = args.match.lower()
        tiles = [p for p in all_tiles if match_lower in p.name.lower()]
        if not tiles:
            print(
                f"No files matching *{args.suffix} and containing '{args.match}' in {input_path}",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"Filtering by name containing '{args.match}' -> {len(tiles)} file(s)")
    else:
        tiles = all_tiles
        if not tiles:
            print(f"No files matching *{args.suffix} in {input_path}", file=sys.stderr)
            sys.exit(1)

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path / "mosaicked.tif"

    output_path = output_path.resolve()
    if output_path.suffix.lower() not in (".tif", ".tiff"):
        output_path = output_path.with_suffix(".tif")

    print(f"Mosaicking {len(tiles)} file(s) from {input_path} -> {output_path}")

    if args.backend == "gdal":
        # Build VRT + COG via GDAL for efficient global mosaics.
        gdal_build_cog_from_vrt(
            tiles=tiles,
            final_output=output_path,
            bounds_str=args.bounds,
            cachemax_mb=args.gdal_cachemax,
            downsample_to_500m=args.downsample_500m,
        )
    else:
        # Python staged/batched mosaic with progress bar (fallback).
        staged_mosaic(
            tiles,
            output_path,
            bounds_str=args.bounds,
            batch_size=args.batch_size,
        )


if __name__ == "__main__":
    main()
