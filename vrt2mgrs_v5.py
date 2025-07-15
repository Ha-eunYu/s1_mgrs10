import argparse
from mgrs import MGRS
import geopandas as gpd
from shapely.geometry import box
import os
import subprocess
import logging
import time
import pyproj
from shapely.ops import transform
import itertools
from shapely.geometry import Polygon, box
from typing import List

# ---------------------------
# Logging Setup
# ---------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
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

# def mgrs_tile_to_polygon(mgrs_code: str, buffer_km: float = 1):
#     m = MGRS()
#     center_code = mgrs_code + "55555"
#     center_lat, center_lon = m.toLatLon(center_code)
#     epsg = mgrs_to_epsg(mgrs_code)
#     project = pyproj.Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True).transform
#     inverse_project = pyproj.Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True).transform
#     x_center, y_center = project(center_lon, center_lat)
#     half_size = 6000
#     geom_utm = box(
#         x_center - half_size, y_center - half_size,
#         x_center + half_size, y_center + half_size
#     )
#     return transform(inverse_project, geom_utm)


def mgrs_tile_to_polygon_10km(mgrs_code: str) -> Polygon:
    m = MGRS()
    ll = m.toLatLon(mgrs_code + "00000")
    ur = m.toLatLon(mgrs_code + "99999")
    return box(ll[1], ll[0], ur[1], ur[0])

def frange(start, stop, step):
    while start <= stop:
        yield round(start, 6)
        start += step

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

def generate_dem_aspect_slope(mgrs_tile, vrt_path, temp_dir, upsample_tr=10):
    epsg = mgrs_to_epsg(mgrs_tile)
    dem_out = os.path.join(temp_dir, f"{mgrs_tile}_dem.tif")
    aspect_out = os.path.join(temp_dir, f"{mgrs_tile}_aspect.tif")
    slope_out = os.path.join(temp_dir, f"{mgrs_tile}_slope.tif")
    roi_geom = mgrs_tile_to_polygon(mgrs_tile, buffer_km=1)
    roi_geojson = os.path.join(temp_dir, f"{mgrs_tile}_roi.geojson")
    gdf = gpd.GeoDataFrame(geometry=[roi_geom], crs='EPSG:4326', index=[0])
    gdf.to_file(roi_geojson, driver='GeoJSON')
    logging.info(f"[{mgrs_tile}] ROI bounds: {roi_geom.bounds}")
    cmd_dem = (
        f"gdalwarp -cutline {roi_geojson} -crop_to_cutline -t_srs EPSG:{epsg} "
        f"-tr {upsample_tr} {upsample_tr} -r lanczos -of GTiff {vrt_path} {dem_out}"
    )
    run_cmd(cmd_dem, step_name=f"Generate DEM {mgrs_tile}")
    cmd_aspect = f"gdaldem aspect {dem_out} {aspect_out}"
    run_cmd(cmd_aspect, step_name=f"Generate Aspect {mgrs_tile}")
    cmd_slope = f"gdaldem slope {dem_out} {slope_out}"
    run_cmd(cmd_slope, step_name=f"Generate Slope {mgrs_tile}")
    os.remove(roi_geojson)
    return [dem_out, aspect_out, slope_out]

def process_mgrs_tiles_10km(geojson_path, vrt_path, temp_dir, upsample_tr=10):
    tiles = get_mgrs_tiles_from_geojson_10km(geojson_path)
    logging.info(f"총 MGRS (10km 타일): {len(tiles)}개")
    for tile in tiles:
        print(f"[DEBUG] Processing tile: {tile} (len={len(tile)})")
        generate_dem_aspect_slope(tile, vrt_path, temp_dir, upsample_tr)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate DEM, slope, and aspect from 10km MGRS tiles with 1km buffer.")
    parser.add_argument("--geojson", required=True, help="Input ROI GeoJSON path")
    parser.add_argument("--vrt", required=True, help="Input VRT file (e.g. COP30.vrt)")
    parser.add_argument("--temp-dir", required=True, help="Temporary output directory for GeoTIFFs")
    parser.add_argument("--upsample-tr", type=int, default=10, help="Target resolution (e.g., 10)")
    args = parser.parse_args()
    process_mgrs_tiles_10km(args.geojson, args.vrt, args.temp_dir, args.upsample_tr)
