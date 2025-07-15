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

def mgrs_tile_to_polygon(mgrs_code: str, buffer_km: float = 1) -> box:
    m = MGRS()

    # 정확히 6자리 코드인지 검사
    if len(mgrs_code) != 6:
        raise ValueError(f"MGRS 코드가 6자리가 아님: '{mgrs_code}'")

    # ll, ur: 각각 격자의 좌측하단, 우측상단 위경도
    ll_lat, ll_lon = m.toLatLon(mgrs_code + "00000")
    ur_lat, ur_lon = m.toLatLon(mgrs_code + "99999")
    geom = box(ll_lon, ll_lat, ur_lon, ur_lat)

    # 해당 MGRS 타일의 UTM zone EPSG 코드 계산
    zone = int(mgrs_code[:2])
    band = mgrs_code[2]
    epsg = 32600 + zone if band >= 'N' else 32700 + zone

    # 위경도 → UTM, 버퍼 → UTM → 다시 위경도
    proj_to_utm = pyproj.Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True).transform
    proj_to_geo = pyproj.Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True).transform

    utm_geom = transform(proj_to_utm, geom)
    buffered_utm = utm_geom.buffer(buffer_km * 1000)  # km→m
    return transform(proj_to_geo, buffered_utm)


    # lower_left_code = mgrs_code + "000000"   # 6 + 9 = 15자리
    # upper_right_code = mgrs_code + "999999"  # 6 + 9 = 15자리

    # ll = m.toLatLon(lower_left_code)
    # ur = m.toLatLon(upper_right_code)
    # geom = box(ll[1], ll[0], ur[1], ur[0])

    # project = pyproj.Transformer.from_crs("EPSG:4326", f"EPSG:{mgrs_to_epsg(mgrs_code)}", always_xy=True).transform
    # geom_utm = transform(project, geom)
    # buffered_geom = geom_utm.buffer(buffer_km * 1000)

    # inverse_project = pyproj.Transformer.from_crs(f"EPSG:{mgrs_to_epsg(mgrs_code)}", "EPSG:4326", always_xy=True).transform
    # return transform(inverse_project, buffered_geom)

# def mgrs_tile_to_polygon(mgrs_code: str, buffer_km: float = 1):
#     """
#     10km MGRS 코드 (예: 52SCF3)에 대해 정확한 경계 사각형 Polygon 반환
#     :param mgrs_code: 6자리 MGRS 코드 (10km)
#     :param buffer_km: UTM에서 거리 기반 버퍼 (기본값 1km)
#     :return: EPSG:4326 기준 Polygon
#     """
#     m = MGRS()

#     # 중심 위경도 추출
#     # center_lat, center_lon = m.toLatLon(mgrs_code)
#     # 중심점 추정: "55"는 easting/northing의 중간
#     center_code = mgrs_code + "55555"  # 10km 타일 안에서 중심을 나타냄
#     center_lat, center_lon = m.toLatLon(center_code)
#     # 위경도 → UTM 변환기
#     epsg = mgrs_to_epsg(mgrs_code)
#     project = pyproj.Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True).transform
#     inverse_project = pyproj.Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True).transform

#     # 중심점을 UTM으로 변환
#     x_center, y_center = project(center_lon, center_lat)

#     # 10km × 10km 타일 (±5000m) 경계 생성
#     half_size = 5000  # meters
#     geom_utm = box(
#         x_center - half_size, y_center - half_size,
#         x_center + half_size, y_center + half_size
#     )

#     # 버퍼 적용
#     buffered_geom = geom_utm.buffer(buffer_km * 1000)

#     # 다시 위경도 좌표계로 변환
#     return transform(inverse_project, buffered_geom)

def get_mgrs_tiles_from_geojson_10km(geojson_path: str) -> list:
    gdf = gpd.read_file(geojson_path)
    bounds = gdf.total_bounds
    m = MGRS()
    tiles = set()
    step = 0.01  # finer sampling
    lat = bounds[1]
    while lat <= bounds[3]:
        lon = bounds[0]
        while lon <= bounds[2]:
            try:
                mgrs_code_full = m.toMGRS(lat, lon, MGRSPrecision=1)  # e.g., 52SCF31
                mgrs_code_6 = mgrs_code_full[:6]                      # → 52SCF3
                tiles.add(mgrs_code_6)
            except Exception:
                pass
            lon += step
        lat += step
    return sorted(tiles)

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

# ---------------------------
# Argument Parsing
# ---------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate DEM, slope, and aspect from 10km MGRS tiles with 1km buffer.")
    parser.add_argument("--geojson", required=True, help="Input ROI GeoJSON path")
    parser.add_argument("--vrt", required=True, help="Input VRT file (e.g. COP30.vrt)")
    parser.add_argument("--temp-dir", required=True, help="Temporary output directory for GeoTIFFs")
    parser.add_argument("--upsample-tr", type=int, default=10, help="Target resolution (e.g., 10)")

    args = parser.parse_args()
    process_mgrs_tiles_10km(args.geojson, args.vrt, args.temp_dir, args.upsample_tr)


# Get-ChildItem *.tif | ForEach-Object { $base = $_.BaseName; & gdalinfo $_.FullName | Out-File "$base.info.txt" }