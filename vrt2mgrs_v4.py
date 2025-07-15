# -*- coding: utf-8 -*-
"""
This script generates 10km MGRS DEM tiles from a VRT file and saves them locally.
Author: DongHyeon Yoon PhD (modified)
Date: 2025-07-15
Version: 1.2.0 (local output only)
"""

import os
import subprocess
import time
import logging
from typing import List
import argparse

import geopandas as gpd
from shapely.geometry import Polygon, box
from mgrs import MGRS

# ---------------------------
# Logging Setup
# ---------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("mgrs_dem_local.log"),
        logging.StreamHandler()
    ]
)

# ---------------------------
# Utilities
# ---------------------------
def run_cmd(cmd: str, step_name: str = ""):
    logging.info(f"[{step_name}] CMD: {cmd}")
    start = time.time()
    subprocess.run(cmd, shell=True, check=True)
    elapsed = time.time() - start
    logging.info(f"[{step_name}] Completed in {elapsed:.2f}s")

def mgrs_to_epsg(mgrs_tile: str) -> int:
    zone = int(mgrs_tile[:2])
    band = mgrs_tile[2]
    return 32600 + zone if band >= 'N' else 32700 + zone

def mgrs_tile_to_polygon_10km(mgrs_code: str) -> Polygon:
    m = MGRS()
    ll = m.toLatLon(mgrs_code + "00000")
    ur = m.toLatLon(mgrs_code + "99999")
    return box(ll[1], ll[0], ur[1], ur[0])

def get_mgrs_tiles_from_geojson_10km(geojson_path: str) -> List[str]:
    gdf = gpd.read_file(geojson_path).to_crs("EPSG:4326")
    bounds = gdf.total_bounds
    m = MGRS()
    tiles = set()

    step = 0.005
    lat = bounds[1]
    while lat <= bounds[3]:
        lon = bounds[0]
        while lon <= bounds[2]:
            try:
                mgrs_code = m.toMGRS(lat, lon, MGRSPrecision=1)[:6]
                tiles.add(mgrs_code)
            except:
                pass
            lon += step
        lat += step

    final_tiles = []
    for t in tiles:
        tile_geom = mgrs_tile_to_polygon_10km(t)
        if gdf.intersects(tile_geom).any():
            final_tiles.append(t)

    return sorted(final_tiles)

def generate_mgrs_dem_local(
    mgrs_tile: str,
    geojson_path: str,
    vrt_path: str,
    output_dir: str,
    upsample_tr: int = 10
):
    epsg = mgrs_to_epsg(mgrs_tile)
    out_name = f"T{mgrs_tile}.tif"
    out_path = os.path.join(output_dir, out_name)

    if os.path.exists(out_path):
        logging.info(f"[{mgrs_tile}] Already exists locally, skipping.")
        return

    os.makedirs(output_dir, exist_ok=True)
    roi_geom = mgrs_tile_to_polygon_10km(mgrs_tile)
    gdf = gpd.read_file(geojson_path)
    subset = gdf[gdf.intersects(roi_geom)]
    if subset.empty:
        logging.info(f"[{mgrs_tile}] No overlap with AOI, skipping.")
        return

    cmd = (
        f"gdalwarp -cutline {geojson_path} -crop_to_cutline -t_srs EPSG:{epsg} "
        f"-tr {upsample_tr} {upsample_tr} -r bilinear -of GTiff {vrt_path} {out_path}"
    )
    run_cmd(cmd, step_name=f"Generate DEM T{mgrs_tile}")

def process_all_tiles_local(
    geojson_path: str,
    vrt_path: str,
    output_dir: str,
    upsample_tr: int = 10
):
    tiles = get_mgrs_tiles_from_geojson_10km(geojson_path)
    logging.info(f"🧩 Total MGRS 10km tiles: {len(tiles)}")
    for tile in tiles:
        generate_mgrs_dem_local(
            mgrs_tile=tile,
            geojson_path=geojson_path,
            vrt_path=vrt_path,
            output_dir=output_dir,
            upsample_tr=upsample_tr
        )

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate 10km MGRS DEM tiles and save locally")
    parser.add_argument("--geojson", required=True, help="Path to AOI GeoJSON file")
    parser.add_argument("--vrt", required=True, help="Path to COP30 VRT file")
    parser.add_argument("--output-dir", required=True, help="Local output directory for DEM tiles")
    parser.add_argument("--upsample-tr", type=int, default=10, help="Target resolution in meters")
    args = parser.parse_args()

    process_all_tiles_local(
        geojson_path=args.geojson,
        vrt_path=args.vrt,
        output_dir=args.output_dir,
        upsample_tr=args.upsample_tr
    )
