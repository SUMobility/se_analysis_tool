from enum import Enum
import pathlib
import partridge as ptg
import datetime as dt
import numpy as np
import pandas as pd
import geopandas as gpd

from MobilityHubDataObjects.utils import safe_is_na, time_to_int

class FeedWrapper:
    # Public
    def __init__(self, feed_path: str | pathlib.Path):
        self.path = pathlib.Path(feed_path).resolve()
        _date, service_ids = ptg.read_busiest_date(str(self.path))
        view = {"trips.txt": {"service_id": service_ids}}
        self.feed = ptg.load_feed(str(self.path), view)
        self.routes = self.feed.routes[
            ["route_id", "agency_id",  "route_short_name", "route_long_name"]
        ].set_index("route_id")
        self.routes["route_aggregated_name"] = self.routes["route_short_name"].where(
            ~self.routes["route_short_name"].isna(),
            other=self.routes["route_long_name"]
        )
    
    def get_stops_with_headways(
        self,
        time_start: dt.time,
        time_end: dt.time,
        percentile: int,
        trip_cutoff: int = 5
    ) -> pd.DataFrame:
        df_stops = self.feed.stops.copy()
        df_stops["headway"] = df_stops.stop_id.map(
            lambda stop_id: self._get_percentile_headway_minutes_for_stop(
                stop_id=stop_id, 
                time_start=time_to_int(time_start),
                time_end=time_to_int(time_end),
                percentile=percentile,
                trip_cutoff=trip_cutoff
            )
        )
        return df_stops.copy()
    
    def get_agency_name(self) -> str | float:
        if len(self.feed.agency.agency_name == 0):
            return self.feed.agency.agency_name.iloc[0]
        else:
            return "Agency has Multiple Names"
    
    def get_agency_url(self) -> str:
        return self.feed.agency.agency_url
    
    def get_pretty_printed_headway(self, stop_headway_object: dict):
        if safe_is_na(stop_headway_object):
            return np.nan
        print(stop_headway_object.keys())
        print(self.feed.routes)
        return ", ".join(
            [f"{self.routes.loc[route_id[0], "route_aggregated_name"]} - {route_id[1]}: {stop_headway_object[route_id]} mins" for route_id in stop_headway_object]
        )       

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
        df_route_and_direction_ids_serving_stop = self.feed.trips.loc[ # inefficient?
            self.feed.trips.trip_id.isin(trip_ids_serving_stop),
            ["route_id", "direction_id"],
        ].drop_duplicates()
        #TODO: need to figure out how to get an id that can be used as a dict to a route efficiently for pretty printing or replace this key with an enum
        #TODO use an enum because they're hashable
        df_route_and_direction_ids_serving_stop["route_direction_combined"] = df_route_and_direction_ids_serving_stop.apply(
            lambda x: (x["route_id"], x["direction_id"]),
            axis=1
        ) #TODO: is an apply bad here??
        df_route_and_direction_ids_serving_stop.set_index("route_direction_combined", inplace=True)
        def get_percentile_headway_for_route_direction(route_id, direction_id):
            trips_for_specified_route_direction = self.feed.trips.loc[
                (self.feed.trips.route_id == route_id) & (self.feed.trips.direction_id == direction_id),
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
                return np.nan
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
    


