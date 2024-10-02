import hashlib
import pathlib
import subprocess
import folium
from pyproj import Transformer, Geod
import numpy as np
import requests
import shapely
import datetime as dt
from playwright.async_api import async_playwright, Playwright

def basic_circle_marker(fillColor: str, **kwargs) -> folium.CircleMarker:
    kwargs_to_pass = dict(kwargs)
    kwargs_to_pass["color"] = "black"
    kwargs_to_pass["fillColor"] = fillColor
    if "fillOpacity" not in kwargs_to_pass:
        kwargs_to_pass["fillOpacity"] = 1
    if "radius" not in kwargs_to_pass:
        kwargs_to_pass["radius"] = 5
    if "weight" not in kwargs_to_pass:
        kwargs_to_pass["weight"] = 0.25
    return folium.CircleMarker(**kwargs_to_pass)

def transform_shapely_geometry(
    from_crs: (str | int),
    to_crs: (str | int),
    geom: (shapely.Geometry)
):
    transformer = Transformer.from_crs(from_crs, to_crs, always_xy=True)
    return shapely.ops.transform(
        transformer.transform,
        geom
    )

def safe_is_na(value: object) -> bool:
     return value is None or (type(value) == float and np.isnan(value))

def get_str_or_na(value : (str | float | None)) -> (str | float):
    if type(value) != str and (np.isnan(value) or value is None):
            return np.nan
    return str(value)

def yes_no_to_bool(value: (str | float | None)) -> (str | float):
    processed = get_str_or_na(value)
    if safe_is_na(processed):
         return np.nan
    elif value == "yes":
         return True
    elif value == "no":
         return False
    else:
         return np.nan

def filter_two_corresponding_arrays(reference, corresponding, other):
    assert len(corresponding) == len(other)
    corresponding_other_map = {corresponding[i]: other[i] for i in range(len(corresponding))}
    intersected = np.intersect1d(np.array(reference), np.array(corresponding))
    other_filtered = [corresponding_other_map[i] for i in intersected]
    return tuple(intersected), tuple(other_filtered)

def time_to_int(time: dt.time):
    return int(time.hour * 3600 + time.minute * 60 + time.second + time.microsecond/1000)

point_or_poly = shapely.Point | shapely.MultiPolygon | shapely.Polygon | shapely.MultiPolygon | shapely.LineString
def small_geodesic_polygons_to_points(
    geom: point_or_poly,
    max_area_square_meters: int,
    ellipsoid: str = "WGS84"
) -> point_or_poly:
    assert type(geom) in (shapely.Point, shapely.MultiPolygon, shapely.Polygon, shapely.MultiPolygon, shapely.LineString)
    # If the geometry is not a polygon, return
    if type(geom) is shapely.Point or type(geom) is shapely.MultiPoint:
         return geom
    
    # Calculate total area of the polygon or multipolygon
    geod = Geod(ellps=ellipsoid)
    def get_geodesic_area(geom: shapely.Polygon):
         return abs(geod.geometry_area_perimeter(geom)[0])
    area = 0
    if type(geom) in [shapely.Polygon, shapely.LineString]:
        area = get_geodesic_area(geom)
    if type(geom) is shapely.MultiPolygon:
        area = sum(map(get_geodesic_area, geom.geoms))
    # If the polygon is small, return it as a point
    if area < max_area_square_meters:
         return geom.centroid
    # Otherwise, return the original object
    return geom

def download_json_safely(url: str): #TODO: consider moving to utils.oy
    r = requests.get(url)
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        print(f"WARN: Error downloading {url}:")
        print(e)
        return None
    try:
        return r.json()
    except requests.JSONDecodeError:
        print(f"WARN: URL {url} did not lead to a valid JSON file. Output was:")
        print(r.text())
        return None

def download_file_with_requests(url: str, output_path: str | pathlib.Path, max_chunk_size: int): #TODO: return type
    sha1_hash = hashlib.new("sha1")
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(pathlib.Path(output_path).resolve(), "wb") as f:
            for chunk in r.iter_content(chunk_size=max_chunk_size): 
                if chunk:
                    f.write(chunk)
                    sha1_hash.update(chunk) 
    print("INFO: Download complete")
    return sha1_hash

def get_sha1_hash(f, max_chunk_size, start_bytes=None):
    sha1_hash = hashlib.new("sha1")
    if start_bytes is not None:
        sha1_hash.update(start_bytes)
    while chunk := f.read(max_chunk_size):
        sha1_hash.update(chunk)
    return sha1_hash

def download_file_with_curl(url: str, output_path: str | pathlib.Path, error_id: str, max_chunk_size: int): #TODO: return type
    curl_command = f"curl -o {pathlib.Path(output_path).resolve()} {url}"
    subprocess.call(curl_command, shell=True) #TODO: internal screaming
    try:
        # Attempt to open the downloaded feed as text - this should fail if the object is actually a feed
        with open(output_path, "rb") as f:
            downloaded = f.read(max_chunk_size)
            try:
                if "ACCESS DENIED" in downloaded.decode("utf-8").upper():
                    print(
                        f"WARN: Curl Download still refused for {error_id}"
                    )
                else:
                    print(
                        f"WARN: The url at {url} for {error_id} responded with the following text rather than a feed"
                    )
                    print(downloaded.decode("utf-8"))
                    return None
            except UnicodeDecodeError:
                # This means that the file isn't text, so it likely is a valid feed
                print("INFO: Curl Download successful")
                # Get hash
                return get_sha1_hash(f, max_chunk_size, start_bytes=downloaded)
    except FileNotFoundError:
        print("WARN: Curl download did not succeed")
    return None

async def download_file_with_playwright(url: str, output_path: str | pathlib.Path, error_id: str, max_chunk_size: int):
    succeeded = False
    async def attempt_download(browser) -> bool:
        succeeded = False
        page = await browser.new_page()
        print(f"INFO: Downloading {url} with Playwright")
        async with page.expect_download() as download_info:
            try:
                await page.goto(url)
                await page.screenshot(path=output_path.with_name(f"{error_id}.png"))
            except:
                download = await download_info.value
                await download.save_as(output_path)
                succeeded = True
        return succeeded

    async with async_playwright() as p:
        print("INFO: About to launch Firefox browser")
        headless_browser = await p.firefox.launch(headless=True)
        print("INFO: Browser launched")
        succeeded = await attempt_download(headless_browser)
        print("INFO: Download attempted")
        await headless_browser.close()
        if not succeeded:
            headed_browser = await p.firefox.launch(headless=False)        
            succeeded = await attempt_download(headed_browser);
            await headed_browser.close()
    
    if succeeded:
        with open(output_path, "rb") as f:
            return get_sha1_hash(f, max_chunk_size)
    return None