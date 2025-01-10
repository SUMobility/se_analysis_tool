from dataclasses import dataclass
from enum import Enum
from typing import Iterable

import numpy as np
import datetime as dt
import geopandas as gpd
import pandas as pd
from scipy.stats import percentileofscore
from MobilityHubDataObjects.constants import GTFS_ROUTE_TYPE_TO_ID_MAP, HIGH_COMFORT_MODES, MODE_CLASSIFICATION_MAP, ModeClassification
from MobilityHubDataObjects.transitWrappers import FeedWrapper
from MobilityHubDataObjects.utils import get_quantile_ranking_series, safe_is_na, time_to_int

CONFIG_MORNING_PEAK_START = "morning_peak_start"
CONFIG_MORNING_PEAK_END = "peak_end"
CONFIG_OFF_PEAK_START = "off_peak_start"
CONFIG_OFF_PEAK_END = "off_peak_end"
CONFIG_EVENING_PEAK_START = "evening_peak_start"
CONFIG_EVENING_PEAK_END = "evening_peak_end"
CONFIG_PEAK_WEIGHT = "peak_weight"
CONFIG_HEADWAY_PERCENTILE = "headway_percentile"
CONFIG_MIN_TRIPS_TO_CALCULATE_HEADWAY = "trip_cutoff"
CONFIG_CLASSIFICATION = "classification_values"
CONFIG_OVERLAP_HEADWAY_MOBILITY_HUB_CUTOFF_BUS = "mh_bus_abs"
CONFIG_OVERLAP_HEADWAY_MOBILITY_HUB_PERCENTILE_BUS = "mh_bus_percentile"
CONFIG_OVERLAP_HEADWAY_TRUNK_CUTOFF_BUS = "trunk_bus_abs"
CONFIG_OVERLAP_HEADWAY_TRUNK_QUANTILE_BUS = "trunk_bus_percentile"
CONFIG_OVERLAP_HEADWAY_TRUNK_RAIL_CUTOFF = "trunk_rail_abs"
CONFIG_TOTAL_FREQUENCY_DIVERGING_ROUTES_MOBILITY_HUB_BUS = "mh_bus_transfer"
CONFIG_TOTAL_FREQUENCY_DIVERGING_ROUTES_TRUNK_BUS = "trunk_bus_transfer"
CONFIG_TOTAL_FREQUENCY_DIVERGING_ROUTES_RAIL = "trunk_rail_transfer"
PERIOD_MORNING_PEAK_NAME = "morning_peak"
PERIOD_EVENING_PEAK_NAME = "evening_peak"
PERIOD_OFF_PEAK_NAME = "off_peak"
MIN_TRIPS = 5

ARBITRARY_DATE = dt.date(1970,1,1)

DEFAULT_FEED_CONFIG = {
    CONFIG_MORNING_PEAK_START: dt.time(hour=7), #TODO: do we also want t
    CONFIG_MORNING_PEAK_END: dt.time(hour=9, minute=0),
    CONFIG_OFF_PEAK_START: dt.time(hour=9, minute=0),
    CONFIG_OFF_PEAK_END: dt.time(hour=16,minute=0),
    CONFIG_EVENING_PEAK_START: dt.time(hour=16, minute=0),
    CONFIG_EVENING_PEAK_END: dt.time(hour=18),
    CONFIG_PEAK_WEIGHT: 0.5,
    CONFIG_HEADWAY_PERCENTILE: 50,
    CONFIG_MIN_TRIPS_TO_CALCULATE_HEADWAY: 5,
    CONFIG_CLASSIFICATION: {
        CONFIG_OVERLAP_HEADWAY_MOBILITY_HUB_CUTOFF_BUS: 15,
        CONFIG_OVERLAP_HEADWAY_MOBILITY_HUB_PERCENTILE_BUS: 0.15,
        CONFIG_TOTAL_FREQUENCY_DIVERGING_ROUTES_MOBILITY_HUB_BUS: 3,
        CONFIG_OVERLAP_HEADWAY_TRUNK_CUTOFF_BUS: 8,
        CONFIG_OVERLAP_HEADWAY_TRUNK_QUANTILE_BUS: 0.05,
        CONFIG_OVERLAP_HEADWAY_TRUNK_RAIL_CUTOFF: 25,
        CONFIG_TOTAL_FREQUENCY_DIVERGING_ROUTES_TRUNK_BUS: 8,
        CONFIG_TOTAL_FREQUENCY_DIVERGING_ROUTES_RAIL: 2,
    },
}

PATTERN_STARTS_PLACEHOLDER = "START"
PATTERN_ENDS_PLACEHOLDER = "END"
PLACEHOLDER_VALUES = (PATTERN_STARTS_PLACEHOLDER, PATTERN_ENDS_PLACEHOLDER)

class StopClassification(Enum):
    NOT_MOBILITY_HUB = 0
    BRANCH = 1
    TRUNK = 2

@dataclass
class Period:
    name: str
    start: dt.time
    end: dt.time

class TransitNetwork:
    stops = np.array([])
    route_id_current_counts = {}

    feeds = {}
    gdf_stops = gpd.GeoDataFrame()
    gdf_processed_stops = gpd.GeoDataFrame()
    df_routes = pd.DataFrame()
    df_stop_times = pd.DataFrame()
    df_service_patterns = pd.DataFrame()

    def __init__ (self, feeds: Iterable[FeedWrapper], local_crs: int, config={}):
        config_to_use = dict(config)
        for key in DEFAULT_FEED_CONFIG:
            if key not in config:
                config_to_use[key] = DEFAULT_FEED_CONFIG[key]
        self.config = config_to_use
        self.local_crs = local_crs
        # Define periods from config
        self.morning_peak = Period(
            PERIOD_MORNING_PEAK_NAME, self.config[CONFIG_MORNING_PEAK_START], self.config[CONFIG_MORNING_PEAK_END]
        )
        self.evening_peak = Period(
            PERIOD_EVENING_PEAK_NAME, self.config[CONFIG_EVENING_PEAK_START], self.config[CONFIG_EVENING_PEAK_END]
        )
        self.off_peak = Period(
            PERIOD_OFF_PEAK_NAME, self.config[CONFIG_OFF_PEAK_START], self.config[CONFIG_OFF_PEAK_END]
        )
        for feed in feeds:
            self.add_feed(feed)
        self.graph_generated = False

    def add_feed(self, feed: FeedWrapper):
        assert feed.feed_loaded
        feed_id = feed.id

        # Build routes df
        routes = feed.df_routes.index.to_numpy()
        routes_transformed = self._transform_route_ids(feed_id, routes)
        routes_map = dict(zip(routes, routes_transformed))
        gdf_feed_stops = feed.gdf_stops
        feed_stop_ids_unique = pd.Series(
            self._transform_stop_ids(feed_id, gdf_feed_stops.index.values),
            index=gdf_feed_stops.index
        )
        stop_geometries = feed.gdf_stops.geometry.to_crs(self.local_crs)
        gdf_new_network_stops = gpd.GeoDataFrame(
            {
                "feed": feed_id,
                "geometry": stop_geometries,
                "stop_id_original": pd.Series(gdf_feed_stops.index, index=gdf_feed_stops.index),
                "stop_id_unique": feed_stop_ids_unique
            },
        )

        route_ids_direction_ids_combined = [
            feed.get_routes_serving_stop(stop_id) for stop_id in gdf_feed_stops.index.to_numpy()
        ]

        gdf_new_network_stops["route_ids_original"] = [x[0] for x in route_ids_direction_ids_combined]
        gdf_new_network_stops["direction_ids"] = [x[1] for x in route_ids_direction_ids_combined]
        gdf_new_network_stops["route_ids_unique"] = gdf_new_network_stops["route_ids_original"].map(
            lambda route_ids: tuple([routes_map[route_id] for route_id in route_ids])
        )
        df_routes = pd.DataFrame(
            {
                "feed": feed_id,
                "route_id_original": routes,
                "route_id_unique": routes_transformed
            }
        )
        service_pattern_ids_original = pd.Series(
            feed.df_service_patterns.index, index=feed.df_service_patterns.index
        )
        df_service_patterns = pd.DataFrame(
            {
                "feed": feed_id,
                "route_id": self._transform_route_ids(feed_id, feed.df_service_patterns["route_id"]),
                "mode": feed.df_service_patterns["route_type"],
                "service_pattern_id_original": service_pattern_ids_original,
                "service_pattern_id_unique": self._transform_service_pattern_ids(
                    feed_id, feed.df_service_patterns["service_pattern_id"]
                ),
            },
        )
        stop_time_stop_ids_original = feed.df_stop_times["stop_id"]
        stop_time_trip_ids_original = feed.df_stop_times["trip_id"]
        stop_time_service_pattern_id_original = feed.df_stop_times[
            "service_pattern_id"
        ]
        df_stop_times = pd.DataFrame({
            "feed": feed_id,
            "stop_id_original": stop_time_stop_ids_original,
            "stop_id_unique": self._transform_stop_ids(feed_id, stop_time_stop_ids_original),
            "trip_id_original": stop_time_trip_ids_original,
            "trip_id_unique": self._transform_trip_ids(feed_id, stop_time_trip_ids_original),
            "service_pattern_id_original": stop_time_service_pattern_id_original,
            "service_pattern_id_unique": self._transform_service_pattern_ids(
                feed_id, stop_time_service_pattern_id_original
            ),
            "arrival_time": feed.df_stop_times["arrival_time"],
            "departure_time": feed.df_stop_times["departure_time"],
            "stop_sequence": feed.df_stop_times["stop_sequence"],
        }).dropna(subset=["service_pattern_id_unique"])
        self.gdf_stops = pd.concat(
            [self.gdf_stops.reset_index(drop=False), gdf_new_network_stops],
            ignore_index=True
        ).set_index("stop_id_unique").drop("index", axis=1, errors="ignore")
        self.df_routes = pd.concat(
            [self.df_routes.reset_index(drop=False), df_routes],
            ignore_index=True
        ).set_index("route_id_unique").drop("index", axis=1, errors="ignore")
        self.df_service_patterns = pd.concat(
            [self.df_service_patterns.reset_index(drop=False), df_service_patterns],
            ignore_index=True
        ).set_index("service_pattern_id_unique").drop("index", axis=1, errors="ignore")
        self.df_stop_times = pd.concat(
            [self.df_stop_times.reset_index(drop=False), df_stop_times],
            ignore_index=True
        ).set_index(["stop_id_unique", "trip_id_unique"]).drop("index", axis=1, errors="ignore")
        self.feeds[feed_id] = feed
        self.graph_generated = False
        print(f"Feed {feed_id} added")

    def get_summary_overlaps_df(self):
        self._create_route_graph_lazily()
        percentile = self.config[CONFIG_HEADWAY_PERCENTILE]
        min_trips = self.config[CONFIG_MIN_TRIPS_TO_CALCULATE_HEADWAY]
        peak_weight = self.config[CONFIG_PEAK_WEIGHT]
        
        periods = (self.morning_peak, self.evening_peak, self.off_peak)
        overlaps_groups = [
            self._get_stop_times_grouped_by_service_overlaps(period, min_trips) for period in periods
        ]
        headway_group_function = lambda group: self._get_headways_for_group_helper(group, percentile)
        # TODO: use a list comprehension here
        frequency_group_functions = [
            lambda group: self._get_frequencies_for_group_helper(group, self.morning_peak),
            lambda group: self._get_frequencies_for_group_helper(group, self.evening_peak),
            lambda group: self._get_frequencies_for_group_helper(group, self.off_peak),

        ]
        df_overlap_headways = self._get_values_from_groups(
            overlaps_groups,
            [period.name for period in periods],
            headway_group_function
        )
        df_overlap_frequencies = self._get_values_from_groups(
            overlaps_groups,
            [period.name for period in periods],
            frequency_group_functions
        )
        df_overlap_summary = pd.concat([
            self._get_weighted_value(
                df_overlap_headways, [self.morning_peak.name, self.evening_peak.name], self.off_peak.name, peak_weight, max=False
            ).rename("weighted_headway"),
            self._get_weighted_value(
                df_overlap_frequencies, [self.morning_peak.name, self.evening_peak.name], self.off_peak.name, peak_weight
            ).rename("weighted_frequency"),
        ], axis=1)
        return df_overlap_summary

    def get_summary_routes_df(self):
        self._create_route_graph_lazily()
        percentile = self.config[CONFIG_HEADWAY_PERCENTILE]
        peak_weight = self.config[CONFIG_PEAK_WEIGHT]
        periods = (self.morning_peak, self.evening_peak, self.off_peak)
        routes_groups = [
            self._get_stop_times_grouped_by_routes(period) for period in periods
        ]
        headway_group_function = lambda group: self._get_headways_for_group_helper(group, percentile)
        # TODO: use a list comprehension here
        frequency_group_functions = [
            lambda group: self._get_frequencies_for_group_helper(group, self.morning_peak),
            lambda group: self._get_frequencies_for_group_helper(group, self.evening_peak),
            lambda group: self._get_frequencies_for_group_helper(group, self.off_peak),
        ]
        df_route_headways = self._get_values_from_groups(
            routes_groups,
            [period.name for period in periods],
            headway_group_function
        )
        df_route_frequencies = self._get_values_from_groups(
            routes_groups,
            [period.name for period in periods],
            frequency_group_functions
        )
        df_route_summary = pd.concat([
            self._get_weighted_value(
                df_route_headways, [self.morning_peak.name, self.evening_peak.name], self.off_peak.name, peak_weight, max=False
            ).rename("weighted_headway"),
            self._get_weighted_value(
                df_route_frequencies, [self.morning_peak.name, self.evening_peak.name], self.off_peak.name, peak_weight
            ).rename("weighted_frequency"),
        ], axis=1)
        return df_route_summary

    def get_headways_by_route(self, period, percentile):
        self._create_route_graph_lazily()
        group_in_period = self._get_stop_times_grouped_by_routes(period)
        return self._get_headways_for_group_helper(group_in_period, percentile)

    def get_headways_by_overlap(self, period, percentile, min_trips=1): #TODO: this shouldn't be 1 by default
        self._create_route_graph_lazily()
        group_in_period = self._get_stop_times_grouped_by_service_overlaps(period, min_trips)
        return self._get_headways_for_group_helper(group_in_period, percentile)
    
    def get_frequencies_by_route(self, period):
        self._create_route_graph_lazily()
        group_in_period = self._get_stop_times_grouped_by_routes(period)
        return self._get_frequencies_for_group_helper(group_in_period, period)
    
    def get_frequencies_by_overlap(self, period, min_trips=1): #TODO: this shouldn't be 1 by default
        self._create_route_graph_lazily()
        group_in_period = self._get_stop_times_grouped_by_service_overlaps(period, min_trips)
        return self._get_frequencies_for_group_helper(group_in_period, period)

    @staticmethod
    def _get_weighted_value(df, peak_names, off_peak_name, peak_weight, max=True):
        df_with_zeroes = df.fillna(0)
        peak_max = None
        if max:
            peak_max = df_with_zeroes[peak_names].max(axis=1)
        else:
            peak_max = df_with_zeroes[peak_names].min(axis=1)
        weighted_values = pd.concat(
            [peak_max * peak_weight, df_with_zeroes[off_peak_name] * (1 - peak_weight)], axis=1
        ).sum(axis=1)
        return weighted_values

    @staticmethod
    def _get_values_from_groups(groups, names, functions):
        result_series_list = []
        functions_iterable = None
        assert len(groups) == len(names)
        if callable(functions):
            functions_iterable = [functions for _ in names]
        else:
            functions_iterable = list(functions)
            assert len(functions_iterable) == len(groups)
        for group, name, function in zip(groups, names, functions_iterable):
            result_series_list.append(
                function(group).rename(name)
            )
        df_results = pd.concat(result_series_list, axis=1)
        return df_results

    def _create_route_graph(self):    
        df_stop_graph = self.df_stop_times.sort_values(
            ["trip_id_unique", "stop_sequence"], kind="stable"
        ).reset_index(
            drop=False
        ).drop_duplicates(
            subset=["stop_id_unique", "service_pattern_id_unique"]
        )[
            ["stop_id_unique", "service_pattern_id_unique", "stop_sequence"]
        ]
        df_service_patterns_by_stop = df_stop_graph.set_index("stop_id_unique")["service_pattern_id_unique"]
        # Get info about the next and previous stop (so we now have a graph of the network)
        service_pattern_stop_groupby = df_stop_graph.groupby("service_pattern_id_unique")["stop_id_unique"]
        df_stop_graph["next_stop"] = service_pattern_stop_groupby.shift(periods=-1)
        df_stop_graph["previous_stop"] = service_pattern_stop_groupby.shift(periods=1)
        # Get a reference to the service patterns at the next and previous stops
        for stop_id_column, new_column_name in (
            ("stop_id_unique", "service_pattern_ids_at_current_stop"),
            ("next_stop", "service_pattern_ids_at_next_stop"), 
            ("previous_stop", "service_pattern_ids_at_previous_stop"),
        ):
            trip_ids = df_stop_graph[stop_id_column].dropna().map(
                lambda stop_id: df_service_patterns_by_stop.loc[stop_id]
            )
            df_stop_graph[new_column_name] = trip_ids.map(
                lambda stop_id_or_series: (stop_id_or_series,) if type(stop_id_or_series) is str else tuple(stop_id_or_series.to_numpy())
            )
        # Get a series of each overlapping service pattern
        df_stop_graph["overlapping_service_patterns"] = pd.Series( #TODO: clean this mess up
            list(zip(
                df_stop_graph["service_pattern_ids_at_current_stop"],
                df_stop_graph["service_pattern_ids_at_next_stop"],
                df_stop_graph["service_pattern_ids_at_previous_stop"]
            )),
            index=df_stop_graph.index
        ).map(
            lambda x: tuple(np.intersect1d(np.intersect1d(x[0], x[1]), x[2]))
        )
        df_stop_graph_ends = df_stop_graph.loc[
            df_stop_graph["next_stop"].isna()
        ].copy()
        df_stop_graph_ends["overlapping_service_patterns"] = pd.Series(
            list(zip(
                df_stop_graph_ends["service_pattern_ids_at_current_stop"],
                df_stop_graph_ends["service_pattern_ids_at_previous_stop"]
            )),
            index=df_stop_graph_ends.index
        ).map(
            lambda x: tuple(np.intersect1d(*x))
        ).copy()
        df_stop_graph_starts = df_stop_graph.loc[
            df_stop_graph["previous_stop"].isna()
        ].copy()
        df_stop_graph_starts["overlapping_service_patterns"] = pd.Series(
            list(zip(
                df_stop_graph_starts["service_pattern_ids_at_current_stop"],
                df_stop_graph_starts["service_pattern_ids_at_next_stop"]
            )),
            index=df_stop_graph_starts.index
        ).map(
            lambda x: tuple(np.intersect1d(*x))
        ).copy()
        df_stop_graph["overlapping_service_patterns"] = df_stop_graph[
            "overlapping_service_patterns"
        ].where(
            ~df_stop_graph["next_stop"].isna(),
            df_stop_graph_ends["overlapping_service_patterns"].reindex(df_stop_graph.index)
        ).where(
            ~df_stop_graph["previous_stop"].isna(),
            df_stop_graph_starts["overlapping_service_patterns"].reindex(df_stop_graph.index)
        )
        #merged_overlaps = df_merged_stops_service_pattern.reset_index().groupby( #TODO: couldn't this just use drop_duplicates()
        #    ["stop_id_unique", "overlapping_service_patterns"]
        #).first().reset_index(level=1)["overlapping_service_patterns"] # TODO: For any patterns that have some intersection, take the union of all of them so that all lists of service patterns are disjoint. also drop empty arrays
        merged_overlaps = df_stop_graph.reset_index(drop=False).drop_duplicates(
            subset=["stop_id_unique", "overlapping_service_patterns"]
        )#.set_index("stop_id_unique")["overlapping_service_patterns"]
        merged_overlaps_condensed = merged_overlaps.groupby("stop_id_unique")["overlapping_service_patterns"].apply(self._condense_overlaps)
        df_merged_overlaps_exploded = merged_overlaps_condensed.explode().reset_index(drop=False)
        df_merged_overlaps_exploded["overlap_id"] = df_merged_overlaps_exploded[
            "stop_id_unique"
        ] + "_" + df_merged_overlaps_exploded.groupby(
            "stop_id_unique"
        )["overlapping_service_patterns"].cumcount().astype(str)
        self.df_stop_graph = df_stop_graph.copy()
        self.df_overlapping_service_patterns = df_merged_overlaps_exploded.set_index("overlap_id")

    def _create_route_graph_lazily(self):
        if self.graph_generated:
            return
        else:
            self._create_route_graph()

    @staticmethod
    def _get_headway_combination_string(headways):
        raise NotImplementedError
    
    def _get_stop_classifications(
            self,
            gdf_stops_with_mode,
            overlap_headways,
            overlap_frequencies,
            classifier_config
        ):
        assert (overlap_frequencies.index == overlap_headways.index).all()
        headway_min = overlap_headways.groupby(level="stop_id_unique").min()
        headway_quantile_min = get_quantile_ranking_series(overlap_headways).groupby(level="stop_id_unique").min()
        frequencies_combined = overlap_frequencies.groupby(level="stop_id_unique").sum()
        #TODO delete me
        assert ((headway_min.index == headway_quantile_min.index) & (headway_min.index == frequencies_combined.index)).all()
        is_transfer = (
            (self.df_stop_graph.groupby("stop_id_unique")["next_stop"].nunique(dropna=True) > 1)
            | self.df_stop_graph.groupby("stop_id_unique")[["next_stop", "previous_stop"]].any().any(axis=1)
        ).loc[headway_min.index] # True if there are multiple overlaps that continue from the current stop
        gdf_stops_copy = gdf_stops_with_mode.copy()
        gdf_stops_copy["classification"] = np.nan
        gdf_stops_copy["mh_from_mode"] = gdf_stops_copy["primary_mode"] == ModeClassification.HIGH_COMFORT
        gdf_stops_copy["mh_from_absolute_headway"] = headway_min <= classifier_config[CONFIG_OVERLAP_HEADWAY_MOBILITY_HUB_CUTOFF_BUS]
        gdf_stops_copy["mh_from_headway_quantile"] = headway_quantile_min <= classifier_config[CONFIG_OVERLAP_HEADWAY_MOBILITY_HUB_PERCENTILE_BUS]
        gdf_stops_copy["mh_from_transfer"] = (
            (frequencies_combined >= classifier_config[CONFIG_TOTAL_FREQUENCY_DIVERGING_ROUTES_MOBILITY_HUB_BUS])
            & is_transfer
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
            headway_min.loc[gdf_stops_mobility_hub_only_high_comfort.index] <= classifier_config[CONFIG_OVERLAP_HEADWAY_TRUNK_RAIL_CUTOFF]
        )
        gdf_stops_mobility_hub_only_high_comfort["trunk_from_transfer"] = (
            frequencies_combined.loc[gdf_stops_mobility_hub_only_high_comfort.index] >= classifier_config[CONFIG_TOTAL_FREQUENCY_DIVERGING_ROUTES_RAIL]
        )
        gdf_stops_mobility_hub_only_other["trunk_from_headway"] = (
            headway_min.loc[gdf_stops_mobility_hub_only_other.index] <= classifier_config[CONFIG_OVERLAP_HEADWAY_TRUNK_CUTOFF_BUS]
        )
        gdf_stops_mobility_hub_only_other["trunk_from_transfer"] = (
            (frequencies_combined.loc[gdf_stops_mobility_hub_only_other.index] >= classifier_config[CONFIG_TOTAL_FREQUENCY_DIVERGING_ROUTES_TRUNK_BUS])
            & is_transfer.loc[gdf_stops_mobility_hub_only_other.index]
        )
        gdf_stops_mobility_hub_only_other["trunk_from_headway_quantile"] = (
            headway_quantile_min.loc[gdf_stops_mobility_hub_only_other.index] <= classifier_config[CONFIG_OVERLAP_HEADWAY_TRUNK_QUANTILE_BUS]
        )
        gdf_stops_mobility_hub = pd.concat(
            [gdf_stops_mobility_hub_only_high_comfort, gdf_stops_mobility_hub_only_other]
        )
        gdf_stops_mobility_hub["is_trunk"] = gdf_stops_mobility_hub[
            ["trunk_from_headway", "trunk_from_transfer", "trunk_from_headway_quantile"]
        ].fillna(False).any(axis=1)
        gdf_stops_with_classification = gdf_stops_copy.merge(
            gdf_stops_mobility_hub[["is_trunk", "trunk_from_headway", "trunk_from_transfer", "trunk_from_headway_quantile"]], how="left", left_index=True, right_index=True, validate="one_to_one"
        )
        gdf_stops_with_classification["classification"] = gdf_stops_with_classification["classification"].fillna(
            gdf_stops_mobility_hub["is_trunk"].replace(
                to_replace=[True, False],
                value=[StopClassification.TRUNK, StopClassification.BRANCH]
            )
        )
        return gdf_stops_with_classification

    def _get_mode_for_stop_ids(self, stop_ids: np.ndarray):
        stop_ids_with_service_patterns = stop_ids[
            np.isin(stop_ids, self.df_stop_times.index.get_level_values("stop_id_unique"))
        ]
        service_patterns_by_stop_id = self.df_stop_times.droplevel(1).loc[
            stop_ids_with_service_patterns, "service_pattern_id_unique"
        ]
        modes_by_stop_id = self.df_service_patterns.loc[service_patterns_by_stop_id.values, "mode"]
        modes_by_stop_id.index = service_patterns_by_stop_id.index
        mode_classification_by_stop_id = modes_by_stop_id.map(MODE_CLASSIFICATION_MAP)
        primary_mode_classification_by_stop_id = mode_classification_by_stop_id.sort_values(
            key=lambda mode_series: mode_series.map({
                ModeClassification.HIGH_COMFORT: 0,
                ModeClassification.BUS: 1,
                ModeClassification.OTHER: 2
            }),
            ascending=True
        ).groupby(level=0).first()
        return primary_mode_classification_by_stop_id.reindex(stop_ids).copy()

    def _get_stop_times_for_time_period(self, start_time: dt.time, end_time: dt.time):
        start_time_seconds = time_to_int(start_time)
        end_time_seconds = time_to_int(end_time)
        return self.df_stop_times.loc[
            (self.df_stop_times["departure_time"] >= start_time_seconds) 
            & (self.df_stop_times["departure_time"] <= end_time_seconds)
        ]

    def _get_stop_times_grouped_by_routes(self, period):
        df_stop_times_in_period = self._get_stop_times_for_time_period(
            period.start, period.end
        )
        df_stop_times_with_routes = df_stop_times_in_period.merge(
            self.df_service_patterns["route_id"],
            how="left",
            left_on="service_pattern_id_unique",
            right_index=True,
            validate="many_to_one"
        )
        df_stop_times_with_routes["combined_time"] = df_stop_times_with_routes["departure_time"].fillna(
            df_stop_times_with_routes["arrival_time"] # Prefer departure time, but allow arrival time where only available
        )
        stop_times_grouped = df_stop_times_with_routes.sort_values("combined_time").groupby(
            ["stop_id_unique", "route_id"]
        )["combined_time"]
        return stop_times_grouped
    
    def _get_stop_times_grouped_by_service_overlaps(self, period, min_trips):
        df_stop_times_in_period = self._get_stop_times_for_time_period(
            period.start, period.end
        )
        df_overlap_ids = self.df_overlapping_service_patterns.explode(
            "overlapping_service_patterns"
        ).rename(columns={"overlapping_service_patterns": "service_pattern_id_unique"})
        df_stop_times_with_overlap_id = df_stop_times_in_period.merge(
            df_overlap_ids.drop_duplicates(subset=["stop_id_unique", "service_pattern_id_unique"]).reset_index(drop=False),
            how="left",
            on=["stop_id_unique", "service_pattern_id_unique"],
            validate="many_to_one",
        )
        # Get values that should be excluded 
        stop_counts = df_stop_times_in_period.index.get_level_values(0).value_counts()
        stops_to_keep = stop_counts.loc[stop_counts >= min_trips].index.values
        df_stop_times_with_overlap_id_filtered = df_stop_times_with_overlap_id.loc[
            df_stop_times_with_overlap_id["stop_id_unique"].isin(stops_to_keep)
        ].copy()
        df_stop_times_with_overlap_id_filtered["combined_time"] = df_stop_times_with_overlap_id_filtered["departure_time"].fillna(
            df_stop_times_with_overlap_id_filtered["arrival_time"].copy() # Prefer departure time, but allow arrival time where only available
        )
        stop_times_grouped = df_stop_times_with_overlap_id_filtered.sort_values("combined_time").groupby(
            ["stop_id_unique", "overlap_id"]
        )["combined_time"]
        return stop_times_grouped

    def _get_headways_for_group_helper(self, stop_times_grouped, percentile):
        headway_function = get_headway_function(percentile)
        headway_seconds = stop_times_grouped.apply(headway_function)
        headway_minutes = headway_seconds / 60.
        return headway_minutes
    
    def _get_frequencies_for_group_helper(self, stop_times_grouped, period):
        time_series_length = (
            dt.datetime.combine(ARBITRARY_DATE, period.end) - dt.datetime.combine(ARBITRARY_DATE, period.start)
        )
        print(period.start, period.end)
        print(time_series_length)
        frequency_function = get_frequency_function(time_series_length)
        frequencies = stop_times_grouped.apply(frequency_function)
        return frequencies

    def _transform_route_ids(self, feed_id, route_ids):
        """Rename the route ids to avoid the possibility of conflict between route ids from different feeds"""
        out = []
        for route_id in route_ids:
            route_id_count = 0
            if route_id in self.route_id_current_counts:
                self.route_id_current_counts[route_id] += 1
                route_id_count = self.route_id_current_counts[route_id]
            route_id_suffix = ""
            while route_id_count > 9:
                route_id_suffix += "9"
                route_id_count %= 10
            route_id_suffix += str(route_id_count)
                                                                     
            base_id = f"{feed_id}_{route_id}_{route_id_suffix}"
            out.append(base_id)
        return out

    @staticmethod
    def _transform_service_pattern_ids(feed_id, service_pattern_ids):
        return concatenate_id_lists(feed_id, service_pattern_ids)

    @staticmethod
    def _transform_trip_ids(feed_id, trip_ids):
        return concatenate_id_lists(feed_id, trip_ids)

    @staticmethod
    def _transform_individual_stop_id(feed_id, stop_id):
        return f"{feed_id}_{stop_id}"

    @staticmethod
    def _transform_stop_ids(feed_id, stop_ids):
        return concatenate_id_lists(feed_id, stop_ids)
    
    @staticmethod
    def _condense_overlaps(overlaps):
        overlaps_no_empty = [overlap for overlap in overlaps if len(overlap) > 0]
        skip_indices = []
        out = []
        for i, overlap_i in enumerate(overlaps_no_empty):
            out_array = overlap_i
            if i in skip_indices:
                continue
            for j, overlap_j in enumerate(overlaps_no_empty):
                if np.intersect1d(overlap_i, overlap_j).size != 0:
                    out_array = np.union1d(out_array, overlap_j)
                    skip_indices.append(j)
            out.append(tuple(out_array))
        return out
# move to utils
def rename_dict_keys(original_dict, key_mapping):
    renamed_dict = {}
    for key, value in original_dict.items():
        renamed_dict[key_mapping.get(key, key)] = value
    return renamed_dict

def concatenate_id_lists(prefix, original_ids):
    return [
        f"{prefix}_{original_id}" if not safe_is_na(original_id) else np.nan 
        for original_id in original_ids
    ]

def get_headway_function(percentile):
    return lambda time_series: get_headway(time_series, percentile)

def get_headway(time_series, percentile):
    headways = (time_series.shift(-1) - time_series).to_numpy()
    if headways.size == 0 or (headways.size == 1 and np.isnan(headways[0])):
        return np.nan
    return np.percentile(
        headways[:-1], percentile
    )

def get_frequency_function(period_length):
    return lambda time_series: get_frequency(time_series, period_length)

def get_frequency(time_series: pd.Series, period_length: dt.timedelta):
    return time_series.count() / (period_length.seconds / 3600.)