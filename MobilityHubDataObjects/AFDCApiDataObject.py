import pathlib

import pandas as pd
from fiona.ogrext import DriverError

from MobilityHubDataObjects.utils import basic_circle_marker, filter_two_corresponding_arrays

from .SpatialDataObject import SpatialDataObject
import geopandas as gpd
from pyogrio.errors import DataSourceError
from pyproj import CRS, Transformer
import shapely
import folium

from .constants import MILES_TO_METERS_FACTOR, METERS_TO_MILES_FACTOR

TEMP_CRS = "EPSG:6423"

class AFDCApiDataObject(SpatialDataObject):
    gdf = gpd.GeoDataFrame
    def __init__(self, source, cache_path, api_key_path):
        # TODO: ping api url to make sure it works
        self.source = source
        self.cache_path = pathlib.Path(cache_path)
        self.api_key_path = api_key_path
        self.num_calls = 0
        try:
            gdf_cache_points = gpd.read_file(self.cache_path)
        except DriverError:
            gdf_cache_points = gpd.GeoDataFrame()
        self.cache_area_path = self.cache_path.parent / f"{self.cache_path.stem}_region.geojson"
        try:
            cache_area = gpd.read_file(self.cache_area_path).geometry.iloc[0]
        except DriverError:
            cache_area = shapely.MultiPolygon() #TODO: figure out a way to use multiple crses (i think this might be hard...)
        self._gdf_cache = gdf_cache_points
        self._cache_area = cache_area

    def _call_afdc_api_ev_chargers(self, latitude: int, longitude: int, radius: float, limit: (int | None) = None):
        print("making api call")
        if self.num_calls > 100:
            raise RuntimeError("too many calls")
        limit_field = limit if limit is not None else "all"
        with open(self.api_key_path, "r") as f:
            api_key = f.readline()
        url = f"{self.source}?api_key={api_key}&latitude={latitude}&longitude={longitude}&radius={radius}&fuel_type=ELEC&limit={limit_field}"
        print(url)
        self.num_calls += 1
        return gpd.read_file(url)

    def get_folium_plot(self) -> folium.GeoJson:
        intended_fields = ["station_name", "street_address", "ev_network", "ev_network_web"]
        intended_aliases = ["Name", "Address", "Network", "Website"]
        fields, aliases = filter_two_corresponding_arrays(self.gdf.columns, intended_fields, intended_aliases)
        afdc_popup = folium.GeoJsonPopup(
            fields=fields,
            aliases=aliases,
            localize=True,
            labels=True,
        )
        afdc_geojson = folium.GeoJson(
            self.gdf[["station_name", "street_address", "ev_network", "ev_network_web", "geometry"]],
            marker=basic_circle_marker("blue"),
            popup=afdc_popup,
        )
        return afdc_geojson

    def load_data(
        self,
        load_area: (shapely.MultiPolygon | shapely.Polygon),
        load_area_crs: int
    ) -> None:
        transformer = Transformer.from_crs(load_area_crs, TEMP_CRS, always_xy=True)
        load_area_transformed = shapely.ops.transform(
            transformer.transform,
            load_area,
        )
        load_area_centroid_lat_lon = shapely.centroid(load_area)
        load_area_centroid = shapely.centroid(load_area_transformed)
        def get_max_distance_from_centroid(geom: shapely.Polygon) -> float:
            return max(
                [
                    shapely.geometry.LineString([load_area_centroid, v]).length
                    for v in geom.exterior.coords
                ]
            )
        load_area_max_distance = -1
        if type(load_area_transformed) is shapely.Polygon:
            load_area_max_distance = get_max_distance_from_centroid(load_area_transformed)
            print(load_area_max_distance)
        else:
            load_area_max_distance = max(map(get_max_distance_from_centroid, load_area_transformed.geoms))
        gdf_afdc_response = self._call_afdc_api_ev_chargers(
            load_area_centroid_lat_lon.y,
            load_area_centroid_lat_lon.x,
            load_area_max_distance * METERS_TO_MILES_FACTOR,
        )
        self.gdf = gdf_afdc_response.loc[gdf_afdc_response.within(load_area)].copy()
        #TODO: fix the below function that adds caching
        """"# Check cache
        transformer = Transformer.from_crs(4269, CRS, always_xy=True)
        search_point_transformed = shapely.Point(*transformer.transform(longitude, latitude))
        search_point_buffer = search_point_transformed.buffer(radius * MILES_TO_METERS_FACTOR)
        print(self._cache_area)
        print(search_point_buffer)
        if self._cache_area.contains(search_point_buffer):
            output = self._gdf_cache[self._gdf_cache.intersects(search_point_buffer)]
            if limit is not None:
                return output.iloc[:limit]
            return output

        api_result = self._call_afdc_api_ev_chargers(latitude, longitude, radius, 10000 if limit is not None and limit < 10000 else limit)
        self._cache_area = self._cache_area.union(search_point_buffer)
        self._gdf_cache = pd.concat([self._gdf_cache, api_result]).drop_duplicates(subset=["id"])
        return api_result"""

    def save_cache_to_file(self):
        self._gdf_cache.to_file(str(self.cache_path.resolve()), index=False)
        with open(self.cache_area_path.resolve(), "w") as f:
            f.write(shapely.to_geojson(self._cache_area))
