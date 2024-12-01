import math
import pathlib
from typing import Callable, Iterable
import folium
import geopandas as gpd
import numpy as np
import pandas as pd
import pygris
from pygris.utils import erase_water
import shapely

from MobilityHubDataObjects import SpatialDataObject
from .ColorMaps import ColorMaps
from .constants import ACS_YEAR, BUFFER_SIZE, EJSCREEN_NAME, GEOID_COLUMN, TIGER_CRS
from .entities import BaseLayerMetric
from MobilityHubDataObjects.utils import transform_shapely_geometry

# Basic colormap that only uses ejscreen functions
def _basic_ejscreen_color_map(df: pd.DataFrame) -> pd.Series:
    color_map = {
            0: "green",
            1: "green",
            2: "green",
            3: "green",
            4: "green",
            5: "green",
            6: "yellow",
            7: "yellow",
            9: "yellow",
            8: "red",
            9: "purple",
            10: "purple"
        }
    p_ptraf_to_color_map = lambda p_ptraf_value: (
        "black" if (
            type(p_ptraf_value) is float and np.isnan(p_ptraf_value)
        ) else color_map[math.floor(p_ptraf_value * 0.1)]
    )
    return df[EJSCREEN_NAME].map(p_ptraf_to_color_map)

_COLOR_MAP_FUNCTIONS = {
    ColorMaps.EJSCREEN_ONLY_COLOR_MAP_ID: _basic_ejscreen_color_map
}


class BaseLayer(SpatialDataObject):
    def __init__(self, metrics: Iterable[BaseLayerMetric], counties_path: str | pathlib.Path, local_crs: int, color_map):
        self.metrics = metrics
        self.counties_path = pathlib.Path(counties_path).resolve()
        self.local_crs = local_crs
        # Get the color map function
        self.color_map_function = _COLOR_MAP_FUNCTIONS[color_map]

    def load_data(
        self,
        load_area: (shapely.MultiPolygon | shapely.Polygon),
        load_area_crs: int
    ):
        # Load a gdf of counties
        gdf_counties = gpd.read_file(
            self.counties_path,
            mask=(transform_shapely_geometry(load_area_crs, TIGER_CRS, load_area))
        )
        # Shrink the load area slightly to avoid getting bordering geometries
        load_area_shrunk = transform_shapely_geometry(
            self.local_crs, load_area_crs, shapely.buffer(
                transform_shapely_geometry(
                    load_area_crs, self.local_crs, load_area
                ), BUFFER_SIZE
            )
        )
        gdf_counties = gdf_counties.loc[gdf_counties.intersects(load_area_shrunk)]
        # Get the TIGER block group data
        gdf_tiger = pd.concat(
            gdf_counties[GEOID_COLUMN].map(
                lambda counties_fips: pygris.block_groups(
                    state=counties_fips[:2],
                    county=counties_fips[2:5],
                    year=ACS_YEAR,
                    cache=True
                )
            ).values
        )
        gdf_tiger = erase_water(gdf_tiger.loc[gdf_tiger.intersects(load_area)])
        gdf_tiger = gdf_tiger.set_index("GEOID")
        metric_names = []
        for metric in self.metrics:
            # Load each metric
            if metric.should_send_block_group_gdf():
                metric.send_block_group_gdf(gdf_tiger)
            if not metric.get_is_loaded():
                metric.load_data(gdf_counties[GEOID_COLUMN])
            metric_series = metric.get_data_for_ids(gdf_tiger.index)
            gdf_tiger[metric_series.name] = metric_series
            metric_names.append(metric_series.name)
        self.metric_names = list(metric_names)
        self.gdf = gdf_tiger.copy()

    def get_folium_plot(self):
        geoid_name = "Block Group GeoID"
        df_to_render = self.gdf.copy()
        df_to_render["color"] = self.color_map_function(
            df_to_render[self.metric_names]
        )
        popup = folium.GeoJsonPopup(
            fields=self.metric_names + [geoid_name]
        )
        return folium.GeoJson(
            df_to_render.reset_index(names=geoid_name),
            style_function=lambda x: {
                "fillColor": x["properties"]["color"],
                "weight": 0.5,
                "color": "grey"
            },
            popup=popup
        ) 
    def get_score_decay_function(self) -> Callable[[float], float]:
        raise NotImplementedError()
    
    def get_scores(self) -> pd.Series:
        raise NotImplementedError
