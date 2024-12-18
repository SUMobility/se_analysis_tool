from typing import Iterable

import folium
import numpy as np
import geopandas as gpd
import pandas as pd
import shapely
from MobilityHubDataObjects import BaseLayer, SpatialDataObject
from MobilityHubDataObjects.BaseLayer.constants import *
from scipy.stats import percentileofscore

from MobilityHubDataObjects.constants import GEODESIC_CRS
from MobilityHubDataObjects.utils import basic_circle_marker, transform_shapely_geometry

USED_BASE_LAYER_METRICS = [
    SMART_LOCATION_JOB_DENSITY_NAME,
    SMART_LOCATION_POPULATION_DENSITY_NAME,
    SMART_LOCATION_RETAIL_ENTERTAINMENT_JOB_DENSITY_NAME,
    SMART_LOCATION_RAW_JOBS_NAME,
]

MIN_DESTINATION_EMPLOYMENT = 1000

OUTPUT_COLUMNS = ["od_type", "trunk_branch_type", "builtin_score", "od_score", "trunk_branch_score", "investment_score"]
OUTPUT_NAMES = ["Is Destination?", "Is Trunk?", "Point Score", "OD Score", "Trunk/Branch Score", "Investment Score"]

class MobilityHubDataObject(SpatialDataObject):
    def __init__(self, component_data_objects: Iterable[SpatialDataObject], base_layer: BaseLayer):
        self.component_data_objects = component_data_objects
        self.base_layer = base_layer
    
    def load_data(self, load_area, load_area_crs):
        assert np.all(
            [data_object.get_is_loaded() for data_object in self.component_data_objects]
        ) #TODO: might be necessary to instead load each object here
        assert np.all([metric in self.base_layer.metric_names for metric in USED_BASE_LAYER_METRICS])
        output_gdfs = []
        for data_object in self.component_data_objects:
            gdf_points = data_object.gdf.loc[
                data_object.gdf.within(transform_shapely_geometry(load_area_crs, GEODESIC_CRS, load_area))
            ]
            gdf_merged_points = assign_base_layer_vars_to_points(
                self.base_layer.gdf, gdf_points, USED_BASE_LAYER_METRICS
            )
            print(data_object.get_scores().index)
            print(data_object.gdf.index)
            print(gdf_merged_points.index)
            gdf_merged_points["builtin_score"] = data_object.get_scores().loc[gdf_merged_points.index].reindex(gdf_merged_points.index) #TODO: check whether this has index matching issues
            print(gdf_merged_points["builtin_score"])
            gdf_merged_points["od_score"] = _generate_od_score(gdf_merged_points)
            gdf_merged_points["trunk_branch_score"] = _generate_trunk_branch_score(gdf_merged_points)
            gdf_merged_points["od_type"] = get_quantile_ranking_series(gdf_merged_points["od_score"]) > 0.8
            gdf_merged_points["trunk_branch_type"] = get_quantile_ranking_series(gdf_merged_points["trunk_branch_score"]) > 0.9
            gdf_merged_points["investment_score"] = np.nan
            # For convenience, make sure the name of gdf_merged_points.geometry is "geometry"
            gdf_merged_points["geometry"] = gdf_merged_points.geometry
            gdf_merged_points.geometry = gdf_merged_points["geometry"]
            output_gdfs.append(gdf_merged_points.copy())
        df_concat = pd.concat(output_gdfs)[[*OUTPUT_COLUMNS, "geometry"]]
        self.gdf = gpd.GeoDataFrame(df_concat.drop("geometry", axis=1), geometry=df_concat["geometry"])
        self._set_is_loaded()
    
    def get_folium_plot(self):
        popup = folium.GeoJsonPopup(
            fields=OUTPUT_COLUMNS, aliases=OUTPUT_NAMES
        )

        def get_color(is_destination, is_trunk):
            if is_destination and is_trunk:
                return "#0000ff"
            if is_destination and not is_trunk:
                return "#00bfff"
            if not is_destination and is_trunk:
                return "#ff00ee"
            if not is_destination and not is_trunk:
                return "#ffb0fa"

        return folium.GeoJson(
            self.gdf,
            marker=basic_circle_marker("black"),
            style_function=lambda x: {
                "fillColor": get_color(x["properties"]["od_type"], x["properties"]["trunk_branch_type"])
            },
            popup=popup
        )

    def get_score_decay_function(self):
        raise NotImplementedError()
    def get_scores(self):
        raise NotImplementedError()


#TODO: move to utils.py
def get_quantile_ranking_series(s: pd.Series) -> pd.Series:
    dropped = s.dropna()
    return pd.Series(
        get_quantile_ranking(dropped), index=dropped.index
    ).reindex(s.index)
def get_quantile_ranking(a: Iterable[float | int]) -> np.array:
    return [percentileofscore(a, i, kind="mean") / 100 for i in a]

def _generate_od_score(gdf_merged_points):
    gdf_base = gpd.GeoDataFrame(
        gdf_merged_points[USED_BASE_LAYER_METRICS], geometry=gdf_merged_points.geometry
    )
    gdf_base["jobs_housing_ratio"] = (
        gdf_base[SMART_LOCATION_JOB_DENSITY_NAME] / gdf_base[SMART_LOCATION_POPULATION_DENSITY_NAME]
    )
    gdf_base["jobs_housing_ratio_quantile"] = get_quantile_ranking_series(
        gdf_base["jobs_housing_ratio"]
    )
    gdf_base["job_density_quantile"] = get_quantile_ranking_series(
        gdf_base[SMART_LOCATION_JOB_DENSITY_NAME]
    )
    gdf_base["retail_job_density_quantile"] = get_quantile_ranking_series(
        gdf_base[SMART_LOCATION_RETAIL_ENTERTAINMENT_JOB_DENSITY_NAME]
    )
    gdf_base["od_score"] = (
        (
            gdf_base["jobs_housing_ratio_quantile"] * 10 
            + gdf_base["job_density_quantile"] * 3 
            + gdf_base["retail_job_density_quantile"] * 3
        ) / 16
    )
    gdf_base["od_score"] = gdf_base["od_score"].where(
        gdf_base[SMART_LOCATION_RAW_JOBS_NAME] >= 1000, 0
    ) #TODO: may need to add an additional factor for small bgs or bgs with a school?
    return gdf_base["od_score"]

def _generate_trunk_branch_score(gdf_merged_points):
     gdf_base = gpd.GeoDataFrame(gdf_merged_points[[*USED_BASE_LAYER_METRICS, "builtin_score"]])
     gdf_base["population_density_quantile"] = get_quantile_ranking_series(
         gdf_base[SMART_LOCATION_POPULATION_DENSITY_NAME]
        )
     gdf_base["job_density_quantile"] = get_quantile_ranking_series(
         gdf_merged_points[SMART_LOCATION_JOB_DENSITY_NAME]
     )
     gdf_base["builtin_score_quantile"] = get_quantile_ranking_series(
         gdf_merged_points["builtin_score"]
     )
     gdf_base["trunk_branch_score"] = (
         (
             gdf_base["population_density_quantile"]
             + gdf_base["job_density_quantile"]
             + gdf_base["builtin_score_quantile"] * 2
         ) / 4
     )

     return gdf_base["trunk_branch_score"]

def assign_base_layer_vars_to_points(gdf_base, gdf_points, base_vars):
    assert np.intersect1d(base_vars, gdf_points.columns).size == 0
    # TODO: this is naive approach
    gdf_points_to_merge = gdf_points.copy().reset_index(names="original_index")
    gdf_merged = gdf_points_to_merge.sjoin(
        gdf_base[[*base_vars, gdf_base.geometry.name]].to_crs(gdf_points_to_merge.crs).copy(),
        how="left",
        predicate="intersects"
    )
    original_len = len(gdf_merged)
    gdf_dropped = gdf_merged.drop_duplicates(
        subset=["original_index"], keep="first"
    ).set_index(
        "original_index"
    ).sort_index()
    print(f"TEST: {original_len - len(gdf_dropped)}")
    return gdf_dropped