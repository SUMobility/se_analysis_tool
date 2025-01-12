from typing import Iterable

import folium
import numpy as np
import geopandas as gpd
import pandas as pd
import shapely
from MobilityHubDataObjects import BaseLayer, GTFSDataObjectLegacy, SpatialDataObject
from MobilityHubDataObjects.BaseLayer.constants import *
from scipy.stats import percentileofscore

from MobilityHubDataObjects.constants import GEODESIC_CRS
from MobilityHubDataObjects.transitWrappers.constants import HIGH_COMFORT_MODES
from MobilityHubDataObjects.utils import basic_circle_marker, get_quantile_ranking_series, transform_shapely_geometry

USED_BASE_LAYER_METRICS = [
    SMART_LOCATION_JOB_DENSITY_NAME,
    SMART_LOCATION_POPULATION_DENSITY_NAME,
    SMART_LOCATION_RETAIL_ENTERTAINMENT_JOB_DENSITY_NAME,
    SMART_LOCATION_RAW_JOBS_NAME,
]

MIN_JOB_DENSITY = 1
POINT_BUFFER_RADIUS = 500

OUTPUT_COLUMNS = ["od_type", "trunk_branch_type", "stop_score", "od_score", "investment_score","primary_mode", "pretty_printed_headway", "min_headway"]
OUTPUT_NAMES = ["Is Destination?", "Is Trunk?", "Point Score", "OD Score", "Investment Score", "Mode", "Headway", "Best Headway"]

class MobilityHubDataObject(SpatialDataObject):
    def __init__(self, transit_stop_data_object: GTFSDataObjectLegacy, base_layer: BaseLayer, local_crs):
        self.transit_stop_data_object = transit_stop_data_object
        self.base_layer = base_layer
        self.local_crs = local_crs
    
    def load_data(self, load_area, load_area_crs):
        assert self.transit_stop_data_object.get_is_loaded()
        assert np.all([metric in self.base_layer.metric_names for metric in USED_BASE_LAYER_METRICS])
        gdf_points = self.transit_stop_data_object.gdf.loc[
            self.transit_stop_data_object.gdf.within(transform_shapely_geometry(load_area_crs, GEODESIC_CRS, load_area))
        ]
        gdf_merged_transit_stops = assign_base_layer_vars_to_points(
            self.base_layer.gdf, gdf_points, USED_BASE_LAYER_METRICS
        ).rename(columns={"score": "stop_score"})
        gdf_merged_transit_stops["od_score"] = _generate_od_score(gdf_merged_transit_stops)
        gdf_merged_transit_stops["od_type"] = get_quantile_ranking_series(gdf_merged_transit_stops["od_score"]) > 0.8
        gdf_merged_transit_stops["trunk_branch_type"] = np.nan
        gdf_merged_transit_stops["investment_score"] = np.nan
        # For convenience, make sure the name of gdf_merged_points.geometry is "geometry"
        gdf_merged_transit_stops["geometry"] = gdf_merged_transit_stops.geometry
        gdf_merged_transit_stops.geometry = gdf_merged_transit_stops["geometry"]
        self.gdf = gdf_merged_transit_stops[[*OUTPUT_COLUMNS, "geometry"]]
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

def _generate_od_score(gdf_merged_points):
    gdf_points = gpd.GeoDataFrame(
        gdf_merged_points[USED_BASE_LAYER_METRICS], geometry=gdf_merged_points.geometry
    )
    gdf_points["jobs_housing_ratio"] = (
        gdf_points[SMART_LOCATION_JOB_DENSITY_NAME] / gdf_points[SMART_LOCATION_POPULATION_DENSITY_NAME]
    )
    gdf_points["jobs_housing_ratio_quantile"] = get_quantile_ranking_series(
        gdf_points["jobs_housing_ratio"]
    )
    gdf_points["job_density_quantile"] = get_quantile_ranking_series(
        gdf_points[SMART_LOCATION_JOB_DENSITY_NAME]
    )
    gdf_points["retail_job_density_quantile"] = get_quantile_ranking_series(
        gdf_points[SMART_LOCATION_RETAIL_ENTERTAINMENT_JOB_DENSITY_NAME]
    )
    gdf_points["od_score"] = (
        (
            gdf_points["jobs_housing_ratio_quantile"] * 10 
            + gdf_points["job_density_quantile"] * 3 
            + gdf_points["retail_job_density_quantile"] * 3
        ) / 16
    )
    gdf_points["od_score"] = gdf_points["od_score"].where(
        (
            (gdf_points[SMART_LOCATION_JOB_DENSITY_NAME] >= MIN_JOB_DENSITY )
            | (gdf_points[SMART_LOCATION_RETAIL_ENTERTAINMENT_JOB_DENSITY_NAME] >=  MIN_JOB_DENSITY)
        ), 0
    ) #TODO: may need to add an additional factor for small bgs or bgs with a school?
    return gdf_points["od_score"]

def _classify_trunk_branch(gdf_stops):
    gdf_stops = gdf_stops.copy()
    raise NotImplementedError()
    


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