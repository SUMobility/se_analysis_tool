from typing import Callable

import pandas as pd

from MobilityHubDataObjects.scoreDecayFunctions import get_linear_decay_function
from MobilityHubDataObjects.scoreFunctions import get_score_constant_value
from MobilityHubDataObjects.utils import basic_circle_marker, filter_two_corresponding_arrays, transform_shapely_geometry

from .SpatialDataObject import SpatialDataObject
import geopandas as gpd
import shapely
import folium

from .constants import METERS_TO_MILES_FACTOR


class AFDCApiDataObject(SpatialDataObject):
    gdf = gpd.GeoDataFrame
    def __init__(self, source, api_key_path, local_projected_crs):
        # TODO: ping api url to make sure it works
        self.source = source
        self.api_key_path = api_key_path
        self.local_projected_crs = local_projected_crs

    def _call_afdc_api_ev_chargers(self, latitude: int, longitude: int, radius: float, limit: (int | None) = None):
        limit_field = limit if limit is not None else "all"
        with open(self.api_key_path, "r") as f:
            api_key = f.readline()
        url = f"{self.source}?api_key={api_key}&latitude={latitude}&longitude={longitude}&radius={radius}&fuel_type=ELEC&limit={limit_field}"
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
        load_area_transformed = transform_shapely_geometry(load_area_crs, self.local_projected_crs, load_area)
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

    def get_scores(self) -> pd.Series:
        return self._get_scores_from_function(get_score_constant_value(5), [])
    
    def get_score_decay_function(self) -> Callable[[float], float]:
        return get_linear_decay_function(500)

