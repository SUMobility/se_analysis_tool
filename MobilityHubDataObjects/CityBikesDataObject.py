from io import StringIO
from typing import Callable
import folium
from folium.features import GeoJson
import numpy as np
import pandas as pd
import geopandas as gpd
import requests
import shapely
from MobilityHubDataObjects import SpatialDataObject, constants
from MobilityHubDataObjects.scoreDecayFunctions import get_linear_decay_function
from MobilityHubDataObjects.utils import basic_circle_marker, download_json_safely, transform_shapely_geometry

COUNTRY_CODE_US = "US"

class CityBikesDataObject(SpatialDataObject):
    def __init__(self, citybikes_url: str) -> None:
        self.citybikes_url = citybikes_url

    def load_data(
        self,
        load_area: (shapely.MultiPolygon | shapely.Polygon),
        load_area_crs: int
    ) -> None:
        load_area_transformed = transform_shapely_geometry(load_area_crs, constants.GEODESIC_CRS, load_area)
        citybikes_feeds_json = download_json_safely(self.citybikes_url + "/v2/networks") #TODO: use urllib for this
        df_citybikes_feeds = pd.DataFrame.from_records(citybikes_feeds_json["networks"])
        df_citybikes_feeds["country"] = df_citybikes_feeds["location"].map(lambda x: x["country"])
        df_citybikes_feeds_us = df_citybikes_feeds.loc[df_citybikes_feeds["country"] == COUNTRY_CODE_US]
        df_citybikes_feeds_us["latitude"] = df_citybikes_feeds_us["location"].map(lambda x: x["latitude"]).copy()
        df_citybikes_feeds_us["longitude"] = df_citybikes_feeds_us["location"].map(lambda x: x["longitude"]).copy()
        gdf_citybikes_feeds_us = gpd.GeoDataFrame(
            df_citybikes_feeds_us,
            geometry=gpd.points_from_xy(df_citybikes_feeds_us["longitude"], df_citybikes_feeds_us["latitude"]),
            crs=constants.GEODESIC_CRS
        )
        #TODO: potentially switch to using a large buffer on the citybikes points, to avoid missing any feeds
        def download_feed(feed_href: str):
            feed_json = download_json_safely(self.citybikes_url + feed_href) #TODO: switch to using urllib for this
            try:
                return feed_json["network"]["stations"]
            except KeyError as e:
                print(f"{feed_href} pointed to an incorrectly formatted feed. Error below:")
                print(e)
                return np.nan
        gdf_citybikes_feeds_in_load_area = gdf_citybikes_feeds_us.loc[gdf_citybikes_feeds_us.within(load_area)]
        gdf_citybikes_feeds_in_load_area["stations"] = gdf_citybikes_feeds_in_load_area["href"].map(
            download_feed
        )
        df_citybikes_stations = gdf_citybikes_feeds_in_load_area.explode("stations", ignore_index=True)
        df_citybikes_stations["longitude"] = df_citybikes_stations["stations"].map(lambda x: x["longitude"]).copy()
        df_citybikes_stations["latitude"] = df_citybikes_stations["stations"].map(lambda x: x["latitude"]).copy()
        df_citybikes_stations["station_name"] = df_citybikes_stations["stations"].map(lambda x: x["name"]).copy()
        df_citybikes_stations["free_bikes"] = df_citybikes_stations["stations"].map(lambda x: x["free_bikes"]).copy()
        df_citybikes_stations["empty_slots"] = df_citybikes_stations["stations"].map(lambda x: x["empty_slots"]).copy()
        df_citybikes_stations["has_ebikes"] = df_citybikes_stations["stations"].map(
            lambda x: "unknown" if "has_ebikes" not in x["extra"] else x["extra"]["has_ebikes"]
        ).copy()
        df_citybikes_stations["capacity"] = df_citybikes_stations["empty_slots"] + df_citybikes_stations["free_bikes"]
        gdf_citybikes_stations = gpd.GeoDataFrame(
            df_citybikes_stations,
            geometry=gpd.points_from_xy(df_citybikes_stations["longitude"], df_citybikes_stations["latitude"]),
            crs=constants.GEODESIC_CRS
        )
        self.gdf = gdf_citybikes_stations.loc[
            gdf_citybikes_stations.within(load_area_transformed),
            ["id", "name", "system", "station_name", "capacity", "has_ebikes", "geometry"]
        ].rename(
            columns={"name": "system_name"}
        )

    def get_scores(self) -> pd.Series:
        return self._get_scores_from_function(lambda x: (2 if x else 0) + 5, ["has_ebikes"])

    def get_score_decay_function(self) -> Callable[[float], float]:
        return get_linear_decay_function(500) 

    def get_folium_plot(self) -> GeoJson:
        citybikes_popup = folium.GeoJsonPopup(
            fields=["system_name", "system", "station_name", 'capacity', "has_ebikes"],
            aliases=["System Name", "Operator","Station Name", "Capacity", "Has Ebikes?"]
        )
        return folium.GeoJson(
            self.gdf,
            popup=citybikes_popup,
            marker=basic_circle_marker("green")
        )