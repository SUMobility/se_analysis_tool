import pathlib
from matplotlib import pyplot as plt
import partridge as ptg
import numpy as np
import datetime as dt
import pandas as pd
from enum import Enum

def get_percentile_headway_minutes_for_stop(
        feed: object, #TODO: use correct type for a feed
        stop_id: str,
        time_start: dt.time,
        time_end: dt.time,
        percentile: int,
        trip_cutoff: int = 5
    ): #TODO: return type
    #TODO: figure out a good way to handle services where there are a substantial nuber of trips but they are all grouped around a short time period
    trip_ids_serving_stop = feed.stop_times.loc[feed.stop_times.stop_id == stop_id, "trip_id"]
    df_route_and_direction_ids_serving_stop = feed.trips.loc[ # inefficient?
        feed.trips.trip_id.isin(trip_ids_serving_stop),
        ["route_id", "direction_id"],
    ].drop_duplicates()
    df_route_and_direction_ids_serving_stop["route_direction_combined"] = df_route_and_direction_ids_serving_stop["route_id"].astype(str) + "_" + df_route_and_direction_ids_serving_stop["direction_id"].astype(str)
    df_route_and_direction_ids_serving_stop.set_index("route_direction_combined", inplace=True)
    def get_percentile_headway_for_route_direction(route_id, direction_id):
        trips_for_specified_route_direction = feed.trips.loc[
            (feed.trips.route_id == route_id) & (feed.trips.direction_id == direction_id),
            "trip_id"
        ]
        df_stop_times_for_specified_stop_route_direction_time = feed.stop_times[ # inefficient?
            ( 
                (feed.stop_times.stop_id == stop_id)
                & feed.stop_times.trip_id.isin(trips_for_specified_route_direction)
                & (feed.stop_times.departure_time > time_start)
                & (feed.stop_times.departure_time < time_end)
            )
        ].sort_values("departure_time")
        if len(df_stop_times_for_specified_stop_route_direction_time) < trip_cutoff:
            #print(
            #    f"WARN: {route_id}, {stop_id} has too few trips ({len(df_stop_times_for_specified_stop_route_direction_time)}) for a meaningful headway to be calculated, returning na"
            #)
            return np.nan
        headway_seconds = df_stop_times_for_specified_stop_route_direction_time.departure_time[1:].values - df_stop_times_for_specified_stop_route_direction_time.departure_time[:-1].values
        headway_minutes = (headway_seconds / 60.).round().astype(int)
        return np.percentile(headway_minutes, percentile)
    df_route_and_direction_ids_serving_stop["percentile_headways"] = df_route_and_direction_ids_serving_stop.apply(
        lambda x: get_percentile_headway_for_route_direction(x["route_id"], x["direction_id"]),
        axis=1
    )
    if df_route_and_direction_ids_serving_stop["percentile_headways"].isna().all():
        return np.nan
    return dict(df_route_and_direction_ids_serving_stop["percentile_headways"].dropna())

def process_feed_file(
    inpath: pathlib.Path | str,
    time_start: dt.time,
    time_end: dt.time,  
    percentile: int,  
) -> pd.DataFrame:
    # Load feed through Partridge
    _date, service_ids = ptg.read_busiest_date(str(inpath))
    view = {"trips.txt": {"service_id": service_ids}}
    feed = ptg.load_feed(inpath, view)
    df_stops = feed.stops.copy()
    df_stops["headway"] = df_stops.stop_id.map(
        lambda stop_id: get_percentile_headway_minutes_for_stop(
            feed=feed,
            stop_id=stop_id, 
            time_start=time_start, 
            time_end=time_end,
            percentile=percentile
        )
    )
    return df_stops.copy()


def get_headway_histogram(feed, stop_id, time_start, time_end):
    trip_ids_serving_stop = feed.stop_times.loc[feed.stop_times.stop_id == stop_id, "trip_id"]
    df_route_and_direction_ids_serving_stop = feed.trips.loc[
        feed.trips.trip_id.isin(trip_ids_serving_stop),
        ["route_id", "direction_id"],
    ]
    test_route = df_route_and_direction_ids_serving_stop.route_id.iloc[0]
    test_direction = df_route_and_direction_ids_serving_stop.direction_id.iloc[0]
    trips_for_specified_route_direction = feed.trips.loc[
            (feed.trips.route_id == test_route) & (feed.trips.direction_id == test_direction),
            "trip_id"
    ].unique()
    df_stop_times_for_specified_stop_route_direction_time = feed.stop_times[
        (
            (feed.stop_times.stop_id == stop_id)
            & feed.stop_times.trip_id.isin(trips_for_specified_route_direction)
            & (feed.stop_times.departure_time > time_start)
            & (feed.stop_times.departure_time < time_end)
        )
    ].sort_values("departure_time")
    headway_seconds = df_stop_times_for_specified_stop_route_direction_time.departure_time[1:].values - df_stop_times_for_specified_stop_route_direction_time.departure_time[:-1].values
    headway_minutes = (headway_seconds / 60.).round().astype(int)
    print(test_route)
    return plt.hist(headway_minutes)

def get_agency_name_url(feed: object): #TODO: return type
    class agency_name_url_enum(Enum):
        name = feed.agency.agency_name
        url = feed.agency.agency_url
    return agency_name_url_enum