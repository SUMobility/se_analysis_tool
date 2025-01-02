from typing import Iterable

import numpy as np
import datetime as dt
import geopandas as gpd
import pandas as pd
from MobilityHubDataObjects.transitWrappers import FeedWrapper
from MobilityHubDataObjects.utils import safe_is_na, time_to_int

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
        #TODO: do something with feeds

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
        })
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
        print(f"Feed {feed_id} added")

    def _get_overlap_headways_frequencies_for_all_periods(self, percentile, periods):
        return self._get_headways_frequencies(percentile, periods, self._get_overlap_headways)

    def _get_headways_frequencies(self, percentile, periods, headway_function):
        new_columns = {}
        for period in periods:
            period_length = dt.datetime(dt.data.today(), period["end"]) - dt.datetime(dt.data.today(), period["start"])
            df_stop_times_in_period = self._get_stop_times_for_time_period(
                period["start"], period["end"]
            )
            headways, frequencies = headway_function(
                df_stop_times_in_period, percentile, period_length
            )
            new_columns[f"headway_{period['name']}"] = headways
            new_columns[f"frequencies_{period['name']}"] = frequencies
        return pd.DataFrame(new_columns)

    def create_route_graph(self):    
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

    @staticmethod
    def _get_headway_combination_string(headways):
        raise NotImplementedError

    def _get_stop_classifications(self, overlap_headways):
        raise NotImplementedError()
        return pd.Series("trunk", index=self.gdf_processed_stops.index)

    def _get_stop_times_for_time_period(self, start_time: dt.time, end_time: dt.time):
        start_time_seconds = time_to_int(start_time)
        end_time_seconds = time_to_int(end_time)
        return self.df_stop_times.loc[
            (self.df_stop_times["departure_time"] >= start_time_seconds) 
            & (self.df_stop_times["departure_time"] <= end_time_seconds)
        ]

    def _get_headways_frequencies_for_service_pattern_overlaps(self, df_stop_times_filtered, percentile, time_series_length):
        df_overlap_ids = self.df_overlapping_service_patterns.explode(
            "overlapping_service_patterns"
        ).rename(columns={"overlapping_service_patterns": "service_pattern_id_unique"})
        df_stop_times_with_overlap_id = df_stop_times_filtered.merge(
            df_overlap_ids.drop_duplicates(subset=["stop_id_unique", "service_pattern_id_unique"]).reset_index(drop=False),
            how="left",
            on=["stop_id_unique", "service_pattern_id_unique"],
            validate="many_to_one",
        )
        headway_function = get_headway_function(percentile)
        frequency_function = get_frequency_function(time_series_length)
        stop_times_grouped = df_stop_times_with_overlap_id.sort_values("departure_time").groupby(
            ["stop_id_unique", "overlap_id"]
        )["departure_time"]
        headways_seconds = stop_times_grouped.apply(headway_function)
        headways_minutes = headways_seconds / 60.
        frequencies = stop_times_grouped.apply(frequency_function)
        return headways_minutes, frequencies

    def _get_headways_frequencies_for_all_routes(self, df_stop_times_filtered, percentile, time_series_length):
        df_stop_times_with_routes = df_stop_times_filtered.merge(
            self.df_service_patterns["route_id"],
            how="left",
            left_on="service_pattern_id_unique",
            right_index=True,
            validate="many_to_one"
        )
        headway_function = get_headway_function(percentile)
        frequency_function = get_frequency_function(time_series_length)
        stop_times_grouped = df_stop_times_with_routes.sort_values("departure_time").groupby(
            ["stop_id_unique", "route_id"]
        )["departure_time"]
        headway_seconds = stop_times_grouped.apply(headway_function)
        headway_minutes = headway_seconds / 60.
        frequencies = stop_times_grouped.apply(frequency_function)
        return headway_minutes, frequencies

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
    return [f"{prefix}_{original_id}" for original_id in original_ids]

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