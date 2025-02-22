from typing import Iterable

import folium
import numpy as np
import geopandas as gpd
import pandas as pd
import shapely
from MobilityHubDataObjects import BaseLayer, SpatialDataObject
from MobilityHubDataObjects.BaseLayer.constants import *
from scipy.stats import percentileofscore

from MobilityHubDataObjects.constants import GEODESIC_CRS, StopClassification
from MobilityHubDataObjects.transitWrappers.constants import HIGH_COMFORT_MODES, ModeClassification
from MobilityHubDataObjects.utils import basic_circle_marker, get_quantile_ranking_series, transform_shapely_geometry

CONFIG_OVERLAP_HEADWAY_MOBILITY_HUB_CUTOFF_BUS = "mh_bus_abs"
CONFIG_OVERLAP_HEADWAY_MOBILITY_HUB_QUANTILE_BUS = "mh_bus_percentile"
CONFIG_OVERLAP_HEADWAY_TRUNK_CUTOFF_BUS = "trunk_bus_abs"
CONFIG_OVERLAP_HEADWAY_TRUNK_QUANTILE_BUS = "trunk_bus_percentile"
CONFIG_OVERLAP_HEADWAY_TRUNK_RAIL_CUTOFF = "trunk_rail_abs"
CONFIG_TOTAL_FREQUENCY_DIVERGING_ROUTES_MOBILITY_HUB_BUS = "mh_bus_transfer"
CONFIG_TOTAL_FREQUENCY_DIVERGING_ROUTES_TRUNK_BUS = "trunk_bus_transfer"
CONFIG_TOTAL_FREQUENCY_DIVERGING_ROUTES_RAIL = "trunk_rail_transfer"

DEFAULT_CONFIG_CLASSIFICATION = {
    CONFIG_OVERLAP_HEADWAY_MOBILITY_HUB_CUTOFF_BUS: 15,
    CONFIG_OVERLAP_HEADWAY_MOBILITY_HUB_QUANTILE_BUS: 0.15,
    CONFIG_TOTAL_FREQUENCY_DIVERGING_ROUTES_MOBILITY_HUB_BUS: 3,
    CONFIG_OVERLAP_HEADWAY_TRUNK_CUTOFF_BUS: 8,
    CONFIG_OVERLAP_HEADWAY_TRUNK_QUANTILE_BUS: 0.05,
    CONFIG_OVERLAP_HEADWAY_TRUNK_RAIL_CUTOFF: 25,
    CONFIG_TOTAL_FREQUENCY_DIVERGING_ROUTES_TRUNK_BUS: 6,
    CONFIG_TOTAL_FREQUENCY_DIVERGING_ROUTES_RAIL: 2,
}

USED_BASE_LAYER_METRICS = [
    SMART_LOCATION_JOB_DENSITY_NAME,
    SMART_LOCATION_POPULATION_DENSITY_NAME,
    SMART_LOCATION_RETAIL_ENTERTAINMENT_JOB_DENSITY_NAME,
    SMART_LOCATION_RAW_JOBS_NAME,
]

MIN_JOB_DENSITY = 1
POINT_BUFFER_RADIUS = 500

OUTPUT_COLUMNS = [
    "od_type", 
    "trunk_branch_type",
    "od_score", 
    "investment_score",
    "mode", 
    "min_overlap_headway", 
    "total_frequency", 
    "adjusted_headway",
    "transfer",
]
OUTPUT_NAMES = [
    "Origin / Destination?", 
    "Trunk / Branch?",
    "OD Score",
    "Investment Score", 
    "Mode", 
    "Best Headway", 
    "Total Frequency",
    "Adjusted Headway",
    "Is Transfer?"
]

class MobilityHubDataObject(SpatialDataObject):
    def __init__(self, transit_stop_data_object, base_layer: BaseLayer, local_crs, **classifier_config):
        self.transit_stop_data_object = transit_stop_data_object
        self.base_layer = base_layer
        self.local_crs = local_crs
        self.classifier_config = {
            **DEFAULT_CONFIG_CLASSIFICATION,
            **classifier_config,
        }
    
    def load_data(self, load_area, load_area_crs):
        assert self.transit_stop_data_object.get_is_loaded()
        assert np.all([metric in self.base_layer.metric_names for metric in USED_BASE_LAYER_METRICS])
        gdf_transit_stops = self.transit_stop_data_object.gdf.loc[
            self.transit_stop_data_object.gdf.within(transform_shapely_geometry(load_area_crs, GEODESIC_CRS, load_area))
        ]
        gdf_merged_transit_stops = assign_base_layer_vars_to_points(
            self.base_layer.gdf, gdf_transit_stops, USED_BASE_LAYER_METRICS, POINT_BUFFER_RADIUS, self.local_crs
        )
        # Correct for cases where headways are unrealistically high (happens when service is very bunched)
        min_reasonable_headway = 60 / gdf_merged_transit_stops["total_frequency"]
        gdf_merged_transit_stops["adjusted_headway"] = gdf_merged_transit_stops["min_overlap_headway"].where(
            gdf_merged_transit_stops["min_overlap_headway"] > min_reasonable_headway, min_reasonable_headway
        )

        gdf_merged_transit_stops["od_score"] = self._generate_od_score(gdf_merged_transit_stops)
        gdf_merged_transit_stops["od_type"] = get_quantile_ranking_series(gdf_merged_transit_stops["od_score"]) > 0.8
        gdf_merged_transit_stops["trunk_branch_type"] = self._classify_trunk_branch(gdf_merged_transit_stops)
        gdf_merged_transit_stops["investment_score"] = np.nan
        # For convenience, make sure the name of gdf_merged_points.geometry is "geometry"
        gdf_merged_transit_stops["geometry"] = gdf_merged_transit_stops.geometry
        gdf_merged_transit_stops.geometry = gdf_merged_transit_stops["geometry"]
        print(gdf_merged_transit_stops.columns)
        self.gdf = gdf_merged_transit_stops[[*OUTPUT_COLUMNS, gdf_merged_transit_stops.geometry.name]]
        self._set_is_loaded()
    
    def get_folium_plot(self):
        popup = folium.GeoJsonPopup(
            fields=OUTPUT_COLUMNS, aliases=OUTPUT_NAMES
        )

        def get_color(is_destination, trunk_branch_type):
            if trunk_branch_type == StopClassification.NOT_MOBILITY_HUB.value:
                return "#c2c2c2"
            if is_destination and trunk_branch_type == StopClassification.TRUNK.value:
                return "#0000ff"
            if is_destination and trunk_branch_type == StopClassification.BRANCH.value:
                return "#00bfff"
            if not is_destination and trunk_branch_type == StopClassification.TRUNK.value:
                return "#ff00ee"
            if not is_destination and trunk_branch_type == StopClassification.BRANCH.value:
                return "#ffb0fa"
        gdf_to_display = self.gdf.to_crs(GEODESIC_CRS).dropna(subset=["mode"])
        gdf_to_display[["mode", "trunk_branch_type"]] = gdf_to_display[["mode", "trunk_branch_type"]].map(lambda x: x.value)
        return folium.GeoJson(
            gdf_to_display,
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

    @staticmethod
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

    def _classify_trunk_branch(self, gdf_stops):
        gdf_stops_copy = gdf_stops.copy()
        #gdf_stops_copy["headway_quantile"] = get_quantile_ranking_series(gdf_stops["min_overlap_headway"])
        headway_array = gdf_stops_copy["adjusted_headway"].dropna().to_numpy()
        mh_headway_quantile_value = np.quantile(
            headway_array, self.classifier_config[CONFIG_OVERLAP_HEADWAY_MOBILITY_HUB_QUANTILE_BUS]
        )
        trunk_headway_quantile_value = np.quantile(
            headway_array, self.classifier_config[CONFIG_OVERLAP_HEADWAY_TRUNK_QUANTILE_BUS]
        )
        print("quantile values", self.classifier_config[CONFIG_OVERLAP_HEADWAY_MOBILITY_HUB_QUANTILE_BUS], self.classifier_config[CONFIG_OVERLAP_HEADWAY_TRUNK_QUANTILE_BUS])
        print(headway_array)
        print("quantile values", mh_headway_quantile_value, trunk_headway_quantile_value)
        gdf_stops_copy["classification"] = np.nan
        gdf_stops_copy["mh_from_mode"] = gdf_stops_copy["mode_classification"] == ModeClassification.HIGH_COMFORT
        gdf_stops_copy["mh_from_absolute_headway"] = (
            (gdf_stops_copy["adjusted_headway"] <= self.classifier_config[CONFIG_OVERLAP_HEADWAY_MOBILITY_HUB_CUTOFF_BUS])
            & (gdf_stops_copy["total_frequency"] >= (60 / self.classifier_config[CONFIG_OVERLAP_HEADWAY_MOBILITY_HUB_CUTOFF_BUS]))
        )
        gdf_stops_copy["mh_from_headway_quantile"] = (
            (gdf_stops_copy["adjusted_headway"] <= mh_headway_quantile_value)
            & (gdf_stops_copy["total_frequency"] >= (60 / mh_headway_quantile_value)) # TODO: use quantile instead
        )
        gdf_stops_copy["mh_from_transfer"] = (
            (gdf_stops_copy["total_frequency"] >= self.classifier_config[CONFIG_TOTAL_FREQUENCY_DIVERGING_ROUTES_MOBILITY_HUB_BUS])
            & gdf_stops_copy["transfer"]
        )
        gdf_stops_copy["is_mh"] = (
            gdf_stops_copy["mh_from_mode"] 
            | gdf_stops_copy["mh_from_absolute_headway"]
            | gdf_stops_copy["mh_from_headway_quantile"]
            | gdf_stops_copy["mh_from_transfer"]
        )
        gdf_stops_copy["classification"] = gdf_stops_copy["is_mh"].replace(
            to_replace=[True, False],
            value=[np.nan, StopClassification.NOT_MOBILITY_HUB]
        )
        gdf_stops_mobility_hub_only_high_comfort = gdf_stops_copy.loc[
            gdf_stops_copy["mh_from_mode"] & gdf_stops_copy["is_mh"], []
        ]
        gdf_stops_mobility_hub_only_other = gdf_stops_copy.loc[
            ~gdf_stops_copy["mh_from_mode"] & gdf_stops_copy["is_mh"], []
        ]
        gdf_stops_mobility_hub_only_high_comfort["trunk_from_headway"] = (
            gdf_stops_copy.loc[
                gdf_stops_mobility_hub_only_high_comfort.index, "adjusted_headway"
            ] <= self.classifier_config[CONFIG_OVERLAP_HEADWAY_TRUNK_RAIL_CUTOFF]
        )
        gdf_stops_mobility_hub_only_high_comfort["trunk_from_transfer"] = (
            (gdf_stops_copy.loc[
                gdf_stops_mobility_hub_only_high_comfort.index, "total_frequency"
            ] >= self.classifier_config[CONFIG_TOTAL_FREQUENCY_DIVERGING_ROUTES_RAIL])
            & gdf_stops_copy.loc[gdf_stops_mobility_hub_only_high_comfort.index, "transfer"]
        )
        gdf_stops_mobility_hub_only_other["trunk_from_headway"] = (
            (gdf_stops_copy.loc[
                gdf_stops_mobility_hub_only_other.index, "adjusted_headway"
            ] <= self.classifier_config[CONFIG_OVERLAP_HEADWAY_TRUNK_CUTOFF_BUS])
            & (gdf_stops_copy["total_frequency"] >= (60 / self.classifier_config[CONFIG_OVERLAP_HEADWAY_TRUNK_CUTOFF_BUS]))
        )
        gdf_stops_mobility_hub_only_other["trunk_from_transfer"] = (
            (gdf_stops_copy.loc[
                gdf_stops_mobility_hub_only_other.index, "total_frequency"
            ] >= self.classifier_config[CONFIG_TOTAL_FREQUENCY_DIVERGING_ROUTES_TRUNK_BUS])
            & gdf_stops_copy["transfer"].loc[gdf_stops_mobility_hub_only_other.index]
        )
        gdf_stops_mobility_hub_only_other["trunk_from_headway_quantile"] = (
            (gdf_stops_copy.loc[
                gdf_stops_mobility_hub_only_other.index, "adjusted_headway"
            ] <= trunk_headway_quantile_value)
            & (gdf_stops_copy["total_frequency"] >= (60 / trunk_headway_quantile_value)) # TODO: change this to be based on the frequency quantile
            
        )
        gdf_stops_mobility_hub = pd.concat(
            [gdf_stops_mobility_hub_only_high_comfort, gdf_stops_mobility_hub_only_other]
        )
        gdf_stops_mobility_hub["is_trunk"] = gdf_stops_mobility_hub[
            ["trunk_from_headway", "trunk_from_transfer", "trunk_from_headway_quantile"]
        ].fillna(False).any(axis=1)
        gdf_stops_with_classification = gdf_stops_copy.merge(
            gdf_stops_mobility_hub[["is_trunk", "trunk_from_headway", "trunk_from_transfer", "trunk_from_headway_quantile"]],
            how="left", left_index=True, right_index=True, validate="one_to_one"
        )
        gdf_stops_with_classification["classification"] = gdf_stops_with_classification["classification"].fillna(
            gdf_stops_mobility_hub["is_trunk"].replace(
                to_replace=[True, False],
                value=[StopClassification.TRUNK, StopClassification.BRANCH]
            )
        )
        return gdf_stops_with_classification["classification"].copy()


def assign_base_layer_vars_to_points(gdf_base, gdf_points, base_vars, radius, projected_crs):
    assert np.intersect1d(base_vars, gdf_points.columns).size == 0
    # TODO: this is naive approach
    gdf_points_to_merge = gdf_points.copy().reset_index(drop=True).to_crs(projected_crs)
    gdf_points_to_merge["unique_id"] = 1
    gdf_points_to_merge["unique_id"] = gdf_points_to_merge["unique_id"].cumsum()
    gdf_points_buffered = gdf_points_to_merge.copy()
    gdf_points_buffered.geometry = gdf_points_to_merge.buffer(radius)
    buffer_area = np.pi * (radius ** 2) #TODO: check this is right and there isn't a unit error
    gdf_overlayed = gdf_points_buffered.overlay(
        gdf_base[[*base_vars, gdf_base.geometry.name]].to_crs(projected_crs).copy(), 
        how="intersection"
    )
    proportion = gdf_overlayed.area.div(buffer_area)
    print(proportion)
    gdf_overlayed[base_vars] = gdf_overlayed[base_vars].mul(proportion, axis=0)
    gdf_base_values_on_points = gdf_overlayed.groupby("unique_id")[base_vars].sum()
    assert gdf_points.index.size == gdf_base_values_on_points.index.size
    gdf_merged = gdf_points_to_merge.merge(
        gdf_base_values_on_points, on="unique_id", how="left", validate="one_to_one"
    ).set_index(gdf_points.index, drop=True)
    return gdf_merged
