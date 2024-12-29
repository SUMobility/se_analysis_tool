import pathlib
import partridge as ptg
import datetime as dt
import numpy as np
import pandas as pd
import geopandas as gpd
import traceback

from MobilityHubDataObjects.constants import GEODESIC_CRS, GTFS_ROUTE_TYPE_TO_ID_MAP, ROUTE_PRIORITY_MAP
from MobilityHubDataObjects.utils import safe_is_na, time_to_int, transform_shapely_geometry


class GTFSFeedWrapperLegacy:
    # Public
    loaded = False
    def __init__(self, feed_path: str | pathlib.Path):
        self.path = pathlib.Path(feed_path).resolve()
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
            self.routes = self.feed.routes[
                ["route_id", "route_type"]
            ].set_index("route_id")
        except AttributeError as e:
            print_bad_gtfs_warning(e)
            return
        if "route_short_name" in self.feed.routes.columns:
            self.routes["route_short_name"] = self.feed.routes["route_short_name"]
        else:
            self.routes["route_short_name"] = np.nan
        if "route_long_name" in self.feed.routes.columns:
            self.routes["route_long_name"] = self.feed.routes["route_long_name"]
        else:
            self.routes["route_long_name"] = np.nan
        self.routes["route_aggregated_name"] = self.routes["route_short_name"].fillna(
            self.routes["route_long_name"].copy().fillna(pd.Series(self.routes.index, index=self.routes.index).dropna())
        )
        self.routes["route_mode_key"] = self.routes["route_type"].map(GTFS_ROUTE_TYPE_TO_ID_MAP)
        self.loaded = True
    
    def get_stops_with_headways(
        self,
        time_start: dt.time,
        time_end: dt.time,
        percentile: int,
        filter_area,
        filter_area_crs,
        trip_cutoff: int = 5,
    ) -> pd.DataFrame:
        if not self.loaded:
            return self._print_not_loaded_error()
        df_stops = self.feed.stops.copy()
        gdf_stops = gpd.GeoDataFrame(
            df_stops,
            geometry=gpd.points_from_xy(df_stops["stop_lon"], df_stops["stop_lat"]),
            crs=GEODESIC_CRS,
        )
        gdf_stops_in_area = gdf_stops.loc[
            gdf_stops.within(transform_shapely_geometry(filter_area_crs, GEODESIC_CRS, filter_area))
        ]
        gdf_stops_in_area["headway"] = gdf_stops_in_area.stop_id.map(
            lambda stop_id: self._get_percentile_headway_minutes_for_stop(
                stop_id=stop_id, 
                time_start=time_to_int(time_start),
                time_end=time_to_int(time_end),
                percentile=percentile,
                trip_cutoff=trip_cutoff
            )
        )
        return pd.DataFrame(gdf_stops_in_area).copy()
    
    def get_agency_name(self) -> str | float:
        if not self.loaded:
            return self._print_not_loaded_error()
        if len(self.feed.agency.agency_name == 0):
            return self.feed.agency.agency_name.iloc[0]
        else:
            return "Agency has Multiple Names"
    
    def get_agency_url(self) -> str:
        if not self.loaded:
            return self._print_not_loaded_error()
        return self.feed.agency.agency_url
    
    def get_pretty_printed_headway(self, stop_headway_object: dict):
        if not self.loaded:
            return self._print_not_loaded_error()
        if safe_is_na(stop_headway_object):
            return np.nan
        def get_headway_mins(headway_mins: int) -> str:
            if headway_mins == -1:
                return "Infrequent Service"
            else:
                return f"{headway_mins} mins"
        return ", ".join(
            [f"{self.routes.loc[route_id[0], "route_aggregated_name"]} - {route_id[1]}: {get_headway_mins(stop_headway_object[route_id])}" for route_id in stop_headway_object]
        ) 

    def get_primary_mode_from_headway(self, stop_headway_object: dict):
        if not self.loaded:
            return self._print_not_loaded_error()
        if safe_is_na(stop_headway_object):
            return np.nan
        route_ids = [route_direction_pair[0] for route_direction_pair in stop_headway_object.keys()]
        if len(route_ids) == 0:
            return np.nan
        route_type_ids = self.routes.loc[route_ids, "route_mode_key"].unique()
        primary_mode_id = sorted(route_type_ids, key=lambda x: ROUTE_PRIORITY_MAP[x])[0]
        return primary_mode_id

    def get_headway_string_from_headway(self, stop_headway_object: dict) -> list[float]:
        if safe_is_na(stop_headway_object):
            return ""
        return ",".join(map(lambda x: str(x), filter(lambda x: x > 0, stop_headway_object.values())))

    def get_last_valid_date(self):
        #TODO: implement
        pass
    
    def get_feed_loaded_correctly(self):
        return self.loaded

    # "Private"
    def _get_percentile_headway_minutes_for_stop(
            self,
            stop_id: str,
            time_start: dt.time,
            time_end: dt.time,
            percentile: int,
            trip_cutoff: int = 5
        ): #TODO: return type
        #TODO: figure out a good way to handle services where there are a substantial nuber of trips but they are all grouped around a short time period
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
        df_route_and_direction_ids_serving_stop["route_direction_combined"] = df_route_and_direction_ids_serving_stop.apply(
            lambda x: (x["route_id"], x["direction_id"]),
            axis=1
        ) #TODO: is an apply bad here??
        df_route_and_direction_ids_serving_stop.set_index("route_direction_combined", inplace=True)
        def get_percentile_headway_for_route_direction(route_id, direction_id):
            trips_with_matching_route_direction = (self.feed.trips.route_id == route_id) & (self.feed.trips.direction_id == direction_id) if has_direction_id else self.feed.trips.route_id == route_id
            trips_for_specified_route_direction = self.feed.trips.loc[
                trips_with_matching_route_direction,
                "trip_id"
            ]
            df_stop_times_for_specified_stop_route_direction_time = self.feed.stop_times[ # inefficient?
                ( 
                    (self.feed.stop_times.stop_id == stop_id)
                    & self.feed.stop_times.trip_id.isin(trips_for_specified_route_direction)
                    & (self.feed.stop_times.departure_time > time_start)
                    & (self.feed.stop_times.departure_time < time_end)
                )
            ].sort_values("departure_time")
            if len(df_stop_times_for_specified_stop_route_direction_time) < trip_cutoff:
                #print(
                #    f"WARN: {route_id}, {stop_id} has too few trips ({len(df_stop_times_for_specified_stop_route_direction_time)}) for a meaningful headway to be calculated, returning na"
                #)
                return -1
            headway_seconds = df_stop_times_for_specified_stop_route_direction_time.departure_time[1:].values - df_stop_times_for_specified_stop_route_direction_time.departure_time[:-1].values
            headway_minutes = (headway_seconds / 60.)
            return int(round(np.percentile(headway_minutes, percentile)))
        df_route_and_direction_ids_serving_stop["percentile_headways"] = df_route_and_direction_ids_serving_stop.apply(
            lambda x: get_percentile_headway_for_route_direction(x["route_id"], x["direction_id"]),
            axis=1
        )
        if df_route_and_direction_ids_serving_stop["percentile_headways"].isna().all():
            return np.nan
        return dict(df_route_and_direction_ids_serving_stop["percentile_headways"].dropna())
    
    def _print_not_loaded_error(self):
        raise RuntimeError("Cannot call any functions on an unloaded feed")



