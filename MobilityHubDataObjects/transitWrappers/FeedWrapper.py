import pathlib
import partridge as ptg
import datetime as dt
import numpy as np
import pandas as pd
import geopandas as gpd
import traceback

from MobilityHubDataObjects.constants import GEODESIC_CRS, GTFS_ROUTE_TYPE_TO_ID_MAP, ROUTE_PRIORITY_MAP
from MobilityHubDataObjects.utils import safe_is_na, time_to_int, transform_shapely_geometry


class FeedWrapper:
    # Public
    feed_loaded = False
    service_loaded = False
    gdf_stops = None
    
    def __init__(
            self,
            feed_path: str | pathlib.Path,
            feed_id: str,
            filter_area,
            filter_area_crs,
        ):
        self.path = pathlib.Path(feed_path).resolve()
        self.id = feed_id
        # Helper functions for printing exceptions 
        def print_partridge_warning(e):
            print(f"WARN: Partridge failed to read a GTFS feed. This is likely because the feed was improperly formatted. Traceback follows:")
            print(traceback.print_exception(e))
        def print_bad_gtfs_warning(e):
            print(f"WARN: GTFS feed could not be read, possibly because it was missing a required field. Exception is below:")
            print(e)
        # Get the service ids associated with the busiest service day in the feed (standard in Partridge example code)
        try:
            _, service_ids = ptg.read_busiest_date(str(self.path))
        except Exception as e:
            print_partridge_warning(e)
            return
        # Create a Partridge feed object for the busiest service day
        view = {"trips.txt": {"service_id": service_ids}}
        try:
            self.feed = ptg.load_feed(str(self.path), view)
        except Exception as e:
            print_partridge_warning(e)
            return
        # Create a routes df with some custom information
        try:
            self.df_routes = self.feed.routes[
                ["route_id", "route_type"]
            ].set_index("route_id")
        except AttributeError as e:
            print_bad_gtfs_warning(e)
            return 
        df_feed_routes_reindexed = self.feed.routes.set_index("route_id").copy()
        if "route_short_name" in df_feed_routes_reindexed:
            self.df_routes["route_short_name"] = df_feed_routes_reindexed["route_short_name"].copy()
        else:
            self.df_routes["route_short_name"] = np.nan
        if "route_long_name" in df_feed_routes_reindexed:
            self.df_routes["route_long_name"] = df_feed_routes_reindexed["route_long_name"].copy()
        else:
            self.df_routes["route_long_name"] = np.nan
        self.df_routes["route_aggregated_name"] = df_feed_routes_reindexed["route_short_name"].fillna(
            self.df_routes["route_long_name"].copy().fillna(
                pd.Series(self.df_routes.index, index=self.df_routes.index).dropna()
            )
        )
        self.df_routes["route_mode_key"] = self.df_routes["route_type"].map(GTFS_ROUTE_TYPE_TO_ID_MAP)

        # Create stops df
        df_stops = self.feed.stops.copy()
        gdf_stops = gpd.GeoDataFrame(
            df_stops,
            geometry=gpd.points_from_xy(df_stops["stop_lon"], df_stops["stop_lat"]),
            crs=GEODESIC_CRS,
        )
        gdf_stops_in_area = gdf_stops.loc[
            gdf_stops.within(transform_shapely_geometry(filter_area_crs, GEODESIC_CRS, filter_area))
        ]
        self.gdf_stops = gdf_stops_in_area.copy().set_index("stop_id")
        self.feed_loaded = True
    
    def load_headways(
        self,
        time_start: dt.time,
        time_end: dt.time,
        percentile: int,
        trip_cutoff: int = 5,
    ) -> pd.Series:
        if not self.feed_loaded:
            return self._print_feed_not_loaded_error()
        headway_column_name = self._get_headway_column_name(time_start, time_end)
        if headway_column_name in self.gdf_stops:
            print("WARN: overriding already loaded headway")
        headway_series = self.gdf["stop_id"].map(
            lambda stop_id: self._get_percentile_headway_minutes_for_stop(
                stop_id=stop_id, 
                time_start=time_to_int(time_start),
                time_end=time_to_int(time_end),
                percentile=percentile,
                trip_cutoff=trip_cutoff
            )
        ).rename(headway_column_name)
        return headway_series
    
    def load_frequencies(
        self,   
        time_start,
        time_end
    ):
        raise NotImplementedError
    
    
    def get_agency_name(self) -> str | float:
        if not self.feed_loaded:
            return self._print_feed_not_loaded_error()
        if len(self.feed.agency.agency_name == 0):
            return self.feed.agency.agency_name.iloc[0]
        else:
            return "Agency has Multiple Names"
    
    def get_agency_url(self) -> str:
        if not self.feed_loaded:
            return self._print_feed_not_loaded_error()
        return self.feed.agency.agency_url
    
    def get_pretty_printed_headway(self, stop_headway_object: dict):
        # TODO: refactor to TransitStop
        if not self.feed_loaded:
            return self._print_feed_not_loaded_error()
        if safe_is_na(stop_headway_object):
            return np.nan
        def get_headway_mins(headway_mins: int) -> str:
            if headway_mins == -1:
                return "Infrequent Service"
            else:
                return f"{headway_mins} mins"
        return ", ".join(
            [f"{self.df_routes.loc[route_id[0], "route_aggregated_name"]} - {route_id[1]}: {get_headway_mins(stop_headway_object[route_id])}" for route_id in stop_headway_object]
        ) 

    def get_primary_mode_from_headway(self, stop_headway_object: dict):
        # Refactor to TransitStop
        if not self.feed_loaded:
            return self._print_feed_not_loaded_error()
        if safe_is_na(stop_headway_object):
            return np.nan
        route_ids = [route_direction_pair[0] for route_direction_pair in stop_headway_object.keys()]
        if len(route_ids) == 0:
            return np.nan
        route_type_ids = self.df_routes.loc[route_ids, "route_mode_key"].unique()
        primary_mode_id = sorted(route_type_ids, key=lambda x: ROUTE_PRIORITY_MAP[x])[0]
        return primary_mode_id

    def get_headway_string_from_headway(self, stop_headway_object: dict) -> list[float]:
        # Refactor to TransitStop
        if safe_is_na(stop_headway_object):
            return ""
        return ",".join(map(lambda x: str(x), filter(lambda x: x > 0, stop_headway_object.values())))

    def get_last_valid_date(self):
        #TODO: implement
        pass
    
    def get_feed_loaded_correctly(self):
        return self.feed_loaded

    def get_routes_serving_stop(
        self,
        stop_id,
    ):
        trip_ids_serving_stop = self.feed.stop_times.loc[self.feed.stop_times.stop_id == stop_id, "trip_id"]
        id_columns = ("route_id",)
        has_direction_id = False
        if "direction_id" in self.feed.trips.columns:
            id_columns = ("route_id", "direction_id")
            has_direction_id = True
        df_route_and_direction_ids_serving_stop = self.feed.trips.loc[ # inefficient?
            self.feed.trips.trip_id.isin(trip_ids_serving_stop),
            id_columns,
        ].drop_duplicates()
        if not has_direction_id:
            df_route_and_direction_ids_serving_stop["direction_id"] = 0
        route_direction_pair = (
            tuple(df_route_and_direction_ids_serving_stop["route_id"].to_numpy()),
            tuple(df_route_and_direction_ids_serving_stop["direction_id"].to_numpy(),)
        )
        return route_direction_pair

    def get_service_patterns_for_route(self, route_id, min_combination_count):
        # Validate that a valid route id has been chosen
        if route_id not in self.df_routes.index:
            raise KeyError(f"Route {route_id} is not present in feed")
        df_trips = self.feed.trips.copy() 
        df_trips_in_route = df_trips.loc[df_trips["route_id"] == route_id]
        df_stop_times = self.feed.stop_times.copy()
        df_stop_times_in_route = df_stop_times.loc[ # potential slow line?
            df_stop_times["trip_id"].isin(df_trips_in_route["trip_id"]) 
        ].sort_values(
            ["trip_id", "stop_sequence"]
        )
        df_trips_in_route["stop_tuple"] = df_trips_in_route["trip_id"].map( #TODO: this should be a groupby instead
            lambda trip_id: tuple(df_stop_times_in_route.loc[df_stop_times_in_route["trip_id"] == trip_id, "stop_id"].to_numpy())
        )
        service_patterns = df_trips_in_route["stop_tuple"].value_counts()
        return list(service_patterns.loc[service_patterns > min_combination_count].index)

    # "Private"
    @staticmethod
    def _get_headway_column_name(time_start: dt.time, time_end: dt.time) -> str:
        """Get the column name for the headway column with the given start and end times"""
        return f"headway_{time_start.hour}:{time_start.min}-{time_end.hour}-{time_end.min}"


    def _print_feed_not_loaded_error(self):
        raise RuntimeError("Cannot call any functions on an unloaded feed")



