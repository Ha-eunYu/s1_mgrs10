#!/usr/bin/env python3
# mgrs_10km_buffer.py

import geopandas as gpd
from shapely.geometry import box, Polygon
from shapely.ops import transform
import pyproj
from mgrs import MGRS
import argparse

def mgrs_tile_to_polygon_10km(mgrs_code: str, buffer_km: float = 1) -> Polygon:
    """
    주어진 10km 단위 MGRS 코드로부터 10kmx10km 격자 + 1km 버퍼(총 11km) 경계 폴리곤 반환.
    """
    m = MGRS()
    # ll, ur: 각각 격자의 좌측하단, 우측상단 위경도
    # ll_lat, ll_lon = m.toLatLon(mgrs_code + "00000000")
    # ur_lat, ur_lon = m.toLatLon(mgrs_code + "99999999")
    # geom = box(ll_lon, ll_lat, ur_lon, ur_lat)

    ll = m.toLatLon(mgrs_code + "000000000")
    ur = m.toLatLon(mgrs_code + "999999999")
    # box(minx, miny, maxx, maxy) 경도(x), 위도(y) 기준으로 사각형 Polygon 생성
    geom = box(ll[1], ll[0], ur[1], ur[0])

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

def get_mgrs_tiles_10km_from_geojson(geojson_path: str) -> list:
    """
    AOI GeoJSON 경계 내에서 10km 단위 MGRS 타일 코드 목록 반환.
    """
    gdf = gpd.read_file(geojson_path)
    lon_min, lat_min, lon_max, lat_max = gdf.total_bounds
    m = MGRS()
    tiles = set()

    # 탐색 스텝: 0.01도(약 1km) 간격으로 샘플링
    lat = lat_min
    while lat <= lat_max:
        lon = lon_min
        while lon <= lon_max:
            try:
                code = m.toMGRS(lat, lon, MGRSPrecision=2)  # 10km 단위
                tiles.add(code)
            except:
                pass
            lon += 0.01
        lat += 0.01

    return sorted(tiles)

def save_tiles_as_geojson(tiles, out_path: str):
    """
    MGRS 타일 리스트를 GeoJSON으로 저장 (버퍼 포함 경계)
    """
    polys = []
    for t in tiles:
        poly = mgrs_tile_to_polygon_10km(t, buffer_km=1)
        polys.append({'tile': t, 'geometry': poly})

    out_gdf = gpd.GeoDataFrame(polys, crs="EPSG:4326")
    out_gdf.to_file(out_path, driver="GeoJSON")
    print(f"✅ 저장 완료: {out_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="10km MGRS 타일 + 1km 버퍼 GeoJSON 생성")
    parser.add_argument("geojson", help="AOI 경계 GeoJSON 파일 경로")
    parser.add_argument("out_geojson", help="출력할 GeoJSON 파일 경로")
    args = parser.parse_args()

    tiles = get_mgrs_tiles_10km_from_geojson(args.geojson)
    print(f"발견된 10km MGRS 타일 수: {len(tiles)}")
    save_tiles_as_geojson(tiles, args.out_geojson)

# sarsen rtc S1_P/S1A_IW_GRDH_1SDV_20241109T092359_20241109T092424_056476_06EC19_6809.SAFE/  IW/VH philippines_cop10.tif --output-urlpath rtc_vh.tif
# sarsen rtc S1_P/S1A_IW_GRDH_1SDV_20241109T092359_20241109T092424_056476_06EC19_6809.SAFE/  IW/VV philippines_cop10.tif --output-urlpath rtc_vv.tif