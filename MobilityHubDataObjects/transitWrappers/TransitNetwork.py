from typing import Iterable

import numpy as np
import datetime as dt
import geopandas as gpd
import pandas as pd
from MobilityHubDataObjects.transitWrappers import FeedWrapper
from MobilityHubDataObjects.utils import safe_is_na

CONFIG_MORNING_PEAK_START = "morning_peak_start"
CONFIG_MORNING_PEAK_END = "peak_end"
CONFIG_OFF_PEAK_START = "off_peak_start"
CONFIG_OFF_PEAK_END = "off_peak_end"
CONFIG_EVENING_PEAK_START = "evening_peak_start"
CONFIG_EVENING_PEAK_END = "evening_peak_end"
CONFIG_PEAK_WEIGHT = "peak_weight"
CONFIG_HEADWAY_PERCENTILE = "headway_percentile"
CONFIG_MIN_TRIPS_TO_CALCULATE_HEADWAY = "trip_cutoff"

MIN_TRIPS = 1

DEFAULT_FEED_CONFIG = {
    CONFIG_MORNING_PEAK_START: dt.time(hour=7), #TODO: do we also want t
    CONFIG_MORNING_PEAK_END: dt.time(hour=9, minute=29),
    CONFIG_OFF_PEAK_START: dt.time(hour=9, minute=30),
    CONFIG_OFF_PEAK_END: dt.time(hour=15,minute=29),
    CONFIG_EVENING_PEAK_START: dt.time(hour=15, minute=30),
    CONFIG_EVENING_PEAK_END: dt.time(hour=19),
    CONFIG_PEAK_WEIGHT: 0.5,
    CONFIG_HEADWAY_PERCENTILE: 80,
    CONFIG_MIN_TRIPS_TO_CALCULATE_HEADWAY: 5,
}

class TransitNetwork:
    stops = np.array([])
    route_id_current_counts = {}

    feeds = {}
    gdf_unprocessed_stops = gpd.GeoDataFrame()
    gdf_processed_stops = gpd.GeoDataFrame()
    df_unprocessed_routes = pd.DataFrame()

    def __init__ (self, feeds: Iterable[FeedWrapper], local_crs: int, config={}):
        config_to_use = dict(config)
        for key in DEFAULT_FEED_CONFIG:
            if key not in config:
                config_to_use[key] = DEFAULT_FEED_CONFIG[key]
        self.config = config_to_use
        self.local_crs = local_crs
        #TODO: do something with feeds

    def add_feed(self, feed: FeedWrapper):
        assert feed.feed_loaded
        """
        morning_headway = feed.load_headways(
            time_start=self.config[CONFIG_MORNING_PEAK_START],
            time_end=self.config[CONFIG_EVENING_PEAK_END],
            percentile=self.config[CONFIG_HEADWAY_PERCENTILE],
            trip_cutoff=self.config[CONFIG_MIN_TRIPS_TO_CALCULATE_HEADWAY]
        )
        off_peak_headway = feed.load_headways(
            time_start=self.config[CONFIG_OFF_PEAK_START],
            time_end=self.config[CONFIG_OFF_PEAK_END],
            percentile=self.config[CONFIG_HEADWAY_PERCENTILE],
            trip_cutoff=self.config[CONFIG_MIN_TRIPS_TO_CALCULATE_HEADWAY]
        )
        evening_headway = feed.load_headways(
            time_start=self.config[CONFIG_OFF_PEAK_START],
            time_end=self.config[CONFIG_EVENING_PEAK_END],
            percentile=self.config[CONFIG_HEADWAY_PERCENTILE],
            trip_cutoff=self.config[CONFIG_MIN_TRIPS_TO_CALCULATE_HEADWAY]
        )
        morning_frequency = feed.load_frequencies(
            time_start=self.config[CONFIG_MORNING_PEAK_START],
            time_end=self.config[CONFIG_MORNING_PEAK_END]
        )
        off_peak_frequency = feed.load_frequencies(
            time_start=self.config[CONFIG_OFF_PEAK_START],
            time_end=self.config[CONFIG_OFF_PEAK_END]
        )
        evening_frequency = feed.load_frequencies(
            time_start=self.config[CONFIG_EVENING_PEAK_START],
            time_end=self.config[CONFIG_EVENING_PEAK_END]
        )"""
        feed_id = feed.id
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

        self.gdf_unprocessed_stops = pd.concat(
            [self.gdf_unprocessed_stops, gdf_new_network_stops],
            ignore_index=True
        )
        self.df_unprocessed_routes = pd.concat(
            [self.df_unprocessed_routes, df_routes],
            ignore_index=True
        )
        self.feeds[feed_id] = feed
        print(f"Feed {feed_id} added")


    def create_route_graph(self):
        # Get one row of the stops df per route
        df_stops_exploded_by_route = pd.DataFrame(self.gdf_unprocessed_stops).explode(
            ["route_ids_original", "route_ids_unique", "direction_ids"]
        ).rename(
            columns={
                "route_ids_original": "route_id_original",
                "route_ids_unique": "route_id_unique",
                "direction_ids": "direction_id"
            }
        )
        # Get all service patterns for all routes
        df_routes_copy = self.df_unprocessed_routes.copy()
        df_routes_copy["service_patterns"] = self.df_unprocessed_routes.apply(
            lambda row: self.feeds[row["feed"]].get_service_patterns_for_route(
                row["route_id_original"],
                MIN_TRIPS
            ),
            axis=1
        )
        # Explode the list of trip combinations
        df_service_patterns = df_routes_copy.explode("service_patterns", ignore_index=True).rename(
            columns={"service_patterns": "service_pattern"}
        )
        # Generate an ID for each unique service pattern
        service_patterns_unique = df_service_patterns["service_pattern"].unique()
        # TODO: redo trip combination ids so that they start at 0 for each route
        service_pattern_to_id_map = dict(zip(
            service_patterns_unique,
            np.arange(service_patterns_unique.size)
        ))
        # Add an id for each service pattern
        df_service_patterns["service_pattern_id_no_route"] = df_service_patterns["service_pattern"].map(service_pattern_to_id_map)
        df_service_patterns[
            "service_pattern_id"
        ] = df_service_patterns["route_id_unique"] + "_" + df_service_patterns["service_pattern_id_no_route"].astype(str)
        # Explode the service pattern df to get one entry per each stop in each service
        df_stops_by_service_pattern = df_service_patterns.explode("service_pattern", ignore_index=True).rename(
            columns={"service_pattern": "stop_id_original"}
        )
        # Get the order of stops in each service pattern
        df_stops_by_service_pattern["stop_order"] = df_stops_by_service_pattern.groupby(
            "service_pattern_id"
        ).cumcount()
        # Add the unique stop id to the service pattern / stop df
        df_stops_by_service_pattern["stop_id_unique"] = df_stops_by_service_pattern.apply(
            lambda row: self._transform_individual_stop_id(row["feed"], row["stop_id_original"]),       
            axis=1
        )
        df_stops_by_service_pattern.set_index("stop_id_unique", inplace=True)
        # Merge stop specific and service pattern specific fields 
        df_merged_stops_service_pattern = df_stops_by_service_pattern.reset_index()[[
            "stop_id_unique", "route_id_unique", "service_pattern_id", "stop_order"
        ]].merge(
            df_stops_exploded_by_route[["stop_id_unique", "route_id_unique", "feed", "stop_id_original", "route_id_original"]],
            how="left",
            on=["route_id_unique", "stop_id_unique"],
        ).sort_values(["route_id_unique", "service_pattern_id", "stop_order"], kind="stable")        
        # Get info about the next and previous stop (so we now have a graph of the network)
        service_pattern_stop_groupby = df_merged_stops_service_pattern.groupby("service_pattern_id")["stop_id_unique"]
        df_merged_stops_service_pattern["next_stop"] = service_pattern_stop_groupby.shift(periods=-1)
        df_merged_stops_service_pattern["previous_stop"] = service_pattern_stop_groupby.shift(periods=1)
        # Get a reference to the service patterns at the next and previous stops
        for stop_id_column, new_column_name in (
            ("stop_id_unique", "service_pattern_ids_at_current_stop"),
            ("next_stop", "service_pattern_ids_at_next_stop"), 
            ("previous_stop", "service_pattern_ids_at_previous_stop"),
        ):
            trip_ids = df_merged_stops_service_pattern[stop_id_column].dropna().map(
                lambda stop_id: df_stops_by_service_pattern.loc[stop_id, "service_pattern_id"]
            )
            df_merged_stops_service_pattern[new_column_name] = trip_ids.map(
                lambda stop_id_or_series: (stop_id_or_series,) if type(stop_id_or_series) is str else tuple(stop_id_or_series.to_numpy())
            )
        
        df_merged_stops_service_pattern["overlapping_service_patterns"] = pd.Series( #TODO: clean this mess up
            list(zip(
                df_merged_stops_service_pattern["service_pattern_ids_at_current_stop"],
                df_merged_stops_service_pattern["service_pattern_ids_at_next_stop"],
                df_merged_stops_service_pattern["service_pattern_ids_at_previous_stop"]
            )),
            index=df_merged_stops_service_pattern.index
        ).map(
            lambda x: tuple(np.intersect1d(np.intersect1d(x[0], x[1]), x[2]))
        )
        #merged_overlaps = df_merged_stops_service_pattern.reset_index().groupby( #TODO: couldn't this just use drop_duplicates()
        #    ["stop_id_unique", "overlapping_service_patterns"]
        #).first().reset_index(level=1)["overlapping_service_patterns"] # TODO: For any patterns that have some intersection, take the union of all of them so that all lists of service patterns are disjoint. also drop empty arrays
        merged_overlaps = df_merged_stops_service_pattern.drop_duplicates(
            subset=["stop_id_unique", "overlapping_service_patterns"]
        ).set_index("stop_id_unique")["overlapping_service_patterns"]
        merged_overlaps_condensed = merged_overlaps.map(self._condense_overlaps)
        self.gdf_processed_stops = df_merged_stops_service_pattern.copy()
        self.overlapping_combinations = merged_overlaps_condensed

    
    def get_headways_for_service_pattern_overlaps(self):
        raise NotImplementedError()
    
    def classify_stops(self):
        raise NotImplementedError()
        
    def get_stop_info(self, stop_id: str):
        raise NotImplementedError()


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
    def _transform_individual_stop_id(feed_id, stop_id):
        return f"{feed_id}_{stop_id}"

    @staticmethod
    def _transform_stop_ids(feed_id, stop_ids):
        return [f"{feed_id}_{stop_id}" for stop_id in stop_ids]
    
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
