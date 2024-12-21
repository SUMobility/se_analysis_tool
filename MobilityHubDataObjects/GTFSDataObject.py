from typing import Callable
import fiona
import folium
import numpy as np
import requests
import shapely
from MobilityHubDataObjects import SpatialDataObject
import datetime as dt
import pandas as pd
import geopandas as gpd
import pathlib
from urllib.parse import urlparse

from MobilityHubDataObjects.GTFSFeedWrapper import GTFSFeedWrapper
from MobilityHubDataObjects.scoreDecayFunctions import get_linear_decay_function
from MobilityHubDataObjects.scoreFunctions import get_score_constant_value, score_transit_stops
from MobilityHubDataObjects.utils import basic_circle_marker, download_file_with_playwright, download_file_with_requests, download_latest_feed_version_from_transitland, filter_two_corresponding_arrays, get_str_or_na, safe_is_na, transform_shapely_geometry, yes_no_to_bool
from MobilityHubDataObjects.constants import GEODESIC_CRS, MODE_COLOR_MAP, ROUTE_TYPE_TO_ROUTE_DISPLAY_NAME_MAP

GTFS_FEEDS_FIELDS_TO_STORE = [
    "name",
    "agency_url",
    "url",
    "raw_feed_path",
    "processed_file_path",
    "last_fetched",
    #"last_valid_date",
    "attribution_url",
    "attribution_text",
    "attribution_instructions",
    "attribution_must_attribute",
    "last_fetch_succeeded",
]
GTFS_STOPS_FIELDS_TO_DISPLAY = [
    "agency_id",
    "agency_name",
    "stop_id",
    "stop_name",
    "primary_mode_display",
    "pretty_printed_headway",
    "score",
]
GTFS_FIELDS_TO_KEEP = [
    *GTFS_STOPS_FIELDS_TO_DISPLAY,

]
GTFS_ALIASES = ["Agency ID", "Agency Name", "Stop ID", "Stop Name", "Primary Mode", "Headway", "Score"]

class GTFSDataObject(SpatialDataObject):
    df_feeds_metadata = None
    load_area = None
    gdf = gpd.GeoDataFrame()

    def __init__(
        self,
        gtfs_cache_path: str | pathlib.Path,
        transitland_url: str,
        max_transitland_cache_life: dt.timedelta,
        time_start: dt.time,
        time_end: dt.time,
        min_headway: int, 
        api_key_path: str,
        gtfs_override_feeds_path: None | str | pathlib.Path = None,
        download_transitland_first: bool = True
    ) -> None:
        
        self.gtfs_cache_path = pathlib.Path(gtfs_cache_path).resolve()
        if gtfs_override_feeds_path is not None:
            self.gtfs_override_feeds_path = pathlib.Path(gtfs_override_feeds_path).resolve()
        else:
            self.gtfs_override_feeds_path = None
        self.transitland_url = transitland_url
        self.time_start = time_start
        self.time_end = time_end
        self.min_headway = min_headway
        #TODO: add api calls to download gtfs files
        self.all_gtfs_paths = None
        self.max_transitland_cache_life = max_transitland_cache_life
        self.transitland_last_queried = None
        with open(api_key_path) as f:
            self.api_key = f.read()
        self.download_transitland_first = download_transitland_first

    async def load_data(
        self,
        load_area: (shapely.MultiPolygon | shapely.Polygon),
        load_area_crs: int
    ) -> None:
        MAX_RESPONSES_PER_PAGE = 100
        MAX_CHUNK_SIZE = 65536
        MAX_CALLS = 100
        def score_stop(headway_dict):
            if safe_is_na(headway_dict):
                return np.nan
            score = 0
            for headway in headway_dict.values():
                if headway == -1:
                    score += 0
                else:
                    # weird fugly sigmoid just as a demo
                    score += max(0, -10 * (1 / (1 + np.e ** (-(headway - 17)/5))) + 10.3229)
            return score
        load_area_transformed = transform_shapely_geometry(load_area_crs, GEODESIC_CRS, load_area)
        # Query Transitland
        transitland_feeds = self._recursively_make_transitland_call(
            MAX_RESPONSES_PER_PAGE,
            load_area_transformed.bounds,
            MAX_CALLS
        )
        df_feeds_metadata = pd.DataFrame
        if self.gtfs_override_feeds_path is not None:
            df_override_feeds = pd.read_csv(self.gtfs_override_feeds_path, index_col=0)
        else:
            df_override_feeds = pd.DataFrame(index=[])
        feeds_metadata_path = self.gtfs_cache_path / "feeds.csv"
        stops_geometry_path = self.gtfs_cache_path / "processed_stops.geojson"
        try:
            df_feeds_metadata = pd.read_csv(
                feeds_metadata_path,
                index_col=0
            )
        except FileNotFoundError:
            print("INFO: Did not load feeds metadata, generating a new file")
            df_feeds_metadata = pd.DataFrame(
                columns=GTFS_FEEDS_FIELDS_TO_STORE,
            )
        try:
            gdf_cached_frequent_stops = gpd.read_file(stops_geometry_path)
        except fiona.errors.DriverError:
            print("INFO: Did not load stops metadata, generating a new file")
            gdf_cached_frequent_stops = gpd.GeoDataFrame(
                columns=["agency_name", "agency_id"]
            )
        frequent_stops_gdf_list = []
        processed_agency_ids = []
        for feed in transitland_feeds:
            feed_id = feed["onestop_id"]
            print(f"INFO: Processing {feed_id}")
            # Get the most recent currently valid feed
            current_feed_version = feed["feed_state"]["feed_version"]
            if not current_feed_version:
                df_feeds_metadata.loc[feed_id, "last_fetch_succeeded"] = False
                continue 
            download_new_file = True

            if feed_id in df_feeds_metadata.index and df_feeds_metadata.at[feed_id, "last_fetch_succeeded"]:
                # The current feed is already in the cache, so we may not need to download a new file
                cached_feed_metadata = df_feeds_metadata.loc[feed_id]
                cached_last_downloaded = dt.datetime.fromisoformat(cached_feed_metadata["last_fetched"])
                #cached_end_of_life = dt.datetime.fromisoformat(cached_feed_metadata["last_valid_date"])
                cached_fetch_status = cached_feed_metadata["last_fetch_succeeded"]
                assert not safe_is_na(cached_last_downloaded) and not safe_is_na(cached_fetch_status)
                if (dt.datetime.now(tz=dt.timezone.utc) - cached_last_downloaded) <= self.max_transitland_cache_life:
                    download_new_file = False
            if download_new_file:
                # Download the feed and update the feed metadata
                feed_url = current_feed_version["url"]
                feed_output_path = self.gtfs_cache_path / f"GTFS_{feed['onestop_id']}.zip"

                if feed_id in df_override_feeds.index:
                    feed_output_path = self.gtfs_cache_path / df_override_feeds.loc[feed_id, "path"]
                else:
                    # Download the feed
                    try:
                        sha1_hash = download_file_with_requests(feed_url, feed_output_path, MAX_CHUNK_SIZE)
                    except requests.HTTPError:
                        sha1_hash = None
                    except requests.exceptions.MissingSchema:
                        print(f"WARN: URL {feed_url} is invalid. Skipping")
                        continue
                    # If download fails and object is configured to download the cached feed from transitland first:
                    if sha1_hash is None and self.download_transitland_first:
                        # Download the cached feed from transitland
                        sha1_hash = download_latest_feed_version_from_transitland(
                            feed_id, feed_output_path, MAX_CHUNK_SIZE, self.api_key
                        )
                    # If download has still failed, try downloading the feed using Playwright
                    if sha1_hash is None:
                        print("INFO: Requests download failed. Will try Playwright")
                        sha1_hash = await download_file_with_playwright(feed_url, 
                            feed_output_path, feed_id, MAX_CHUNK_SIZE)
                    # If download has still failed, try downloading the feed using Requests
                    if sha1_hash is None and not self.download_transitland_first:
                        sha1_hash = download_latest_feed_version_from_transitland(
                            feed_id, feed_output_path, MAX_CHUNK_SIZE, self.api_key
                        )
                    # If the download has still failed, skip this feed
                    if sha1_hash is None:
                        print(f"WARN: Download for {feed_id} failed even with Playwright")
                        df_feeds_metadata.loc[feed_id, "last_fetch_succeeded"] = False
                        continue
                    if sha1_hash is not None and sha1_hash.hexdigest() != current_feed_version["sha1"]:
                        print(
                            f"WARN: For {feed['onestop_id']}, the hash {sha1_hash.hexdigest()} does not match the provided hash from Transitland {current_feed_version['sha1']}"
                        )
                feed_last_fetched = dt.datetime.now(tz=dt.timezone.utc)
                #feed_end_of_life_dt = dt.datetime.fromisoformat(df_current_feed_version["latest_calendar_date"])
                feed_attribution_url = get_str_or_na(feed["license"]["url"])
                feed_attribution_text = get_str_or_na(feed["license"]["attribution_text"])
                feed_attribution_instructions = get_str_or_na(feed["license"]["attribution_instructions"])
                feed_must_attribute = yes_no_to_bool(feed["license"]["use_without_attribution"])
                #TODO: figure out feed object to get agency name and url and run feedutils functions without needing to load a new feed each time
                # Process frequent stops
                feed_object = GTFSFeedWrapper(feed_output_path)
                if not feed_object.get_feed_loaded_correctly():
                    df_feeds_metadata.loc[feed_id, "last_fetch_succeeded"] = False
                    continue 
                feed_name = feed_object.get_agency_name()
                print(f"FEED NAME: {feed_name}")
                feed_agency_url = feed_object.get_agency_url()
                df_feeds_metadata.loc[feed_id] = {
                    "name": feed_name,
                    "agency_url": feed_agency_url,
                    "url": feed_url,
                    "raw_feed_path": feed_output_path,
                    "last_fetched": feed_last_fetched,
                    #"last_valid_date": feed_end_of_life_dt,
                    "attribution_url": feed_attribution_url,
                    "attribution_text": feed_attribution_text,
                    "attribution_instructions": feed_attribution_instructions,
                    "attribution_must_attribute": feed_must_attribute,
                    "last_fetch_succeeded": True,
                }

                # Get stop frequencies
                print("INFO: Processing stops - this takes a while")
                df_feed_stops_with_headway = feed_object.get_stops_with_headways(
                    time_start=self.time_start,
                    time_end=self.time_end,
                    percentile=80,
                    filter_area=load_area_transformed,
                    filter_area_crs=GEODESIC_CRS,
                    trip_cutoff=5,
                )
                # Get displayed data about each stop
                if df_feed_stops_with_headway is not None:
                    df_feed_stops_with_headway["min_headway"] = df_feed_stops_with_headway["headway"].map(
                        lambda x: np.nan if safe_is_na(x) else min(x.values())
                    ).astype(np.float64) # This astype is necessary, since otherwise Geopandas will delete the column when saved to geojson
                    df_feed_stops_with_headway["pretty_printed_headway"] = df_feed_stops_with_headway["headway"].map(
                        feed_object.get_pretty_printed_headway
                    )
                    df_feed_stops_with_headway["headway_string"] = df_feed_stops_with_headway["headway"].map(feed_object.get_headway_string_from_headway)
                    df_feed_stops_with_headway["score"] = df_feed_stops_with_headway["headway"].map(score_stop)
                    df_feed_stops_with_headway["primary_mode"] = df_feed_stops_with_headway["headway"].map(
                        feed_object.get_primary_mode_from_headway
                    )
                    df_feed_stops_with_headway["primary_mode_display_name"] = df_feed_stops_with_headway["primary_mode"].map(
                        ROUTE_TYPE_TO_ROUTE_DISPLAY_NAME_MAP
                    )
                    df_frequent_stops = df_feed_stops_with_headway.loc[df_feed_stops_with_headway["min_headway"] <= self.min_headway]
                    gdf_frequent_stops = gpd.GeoDataFrame(
                        df_frequent_stops,
                        geometry=gpd.points_from_xy(df_frequent_stops["stop_lon"], df_frequent_stops["stop_lat"]),
                    )
                    if len(gdf_frequent_stops) > 0:
                        gdf_frequent_stops.loc[:, "agency_name"] = feed_name
                        gdf_frequent_stops.loc[:, "agency_id"] = feed_id
                        gdf_frequent_stops.crs = GEODESIC_CRS
                        gdf_frequent_stops_in_area = gdf_frequent_stops.loc[gdf_frequent_stops.within(load_area_transformed)]
                        frequent_stops_gdf_list.append(
                            gdf_frequent_stops_in_area
                        )
                    processed_agency_ids.append(feed_id)        
        # Merge newly downloaded and cached stops
        print(f"PRINTING ALL PROCESSED AGENCY IDS: {", ".join(processed_agency_ids)}")
        if len(frequent_stops_gdf_list) > 0:
            gdf_new_frequent_stops = pd.concat(frequent_stops_gdf_list)
            print(f"AGENCIES: {gdf_new_frequent_stops["agency_id"].unique()}")
            gdf_cached_frequent_stops_to_keep = gpd.GeoDataFrame(columns=gdf_new_frequent_stops.columns)
            if len(gdf_cached_frequent_stops) > 0:
                gdf_cached_frequent_stops_to_keep = gdf_cached_frequent_stops.loc[
                    ~gdf_cached_frequent_stops["agency_id"].isin(processed_agency_ids)
                ]
            assert (
                np.intersect1d(
                    gdf_new_frequent_stops["agency_id"].unique(),
                    gdf_cached_frequent_stops_to_keep["agency_id"].unique(),
                ).size == 0
            )
            print("CACHED", list(gdf_cached_frequent_stops.columns))
            print("NEW", list(gdf_new_frequent_stops.columns))
            self.gdf = pd.concat(
                [gdf_new_frequent_stops, gdf_cached_frequent_stops_to_keep]
            ).drop("headway", axis=1)
            # Save result to a file
            self.gdf.to_file(stops_geometry_path)
        else:
            self.gdf = gdf_cached_frequent_stops
        self.df_feeds_metadata = df_feeds_metadata
        # Save stops and feed metadata to file
        df_feeds_metadata.to_csv(feeds_metadata_path)
        self._set_is_loaded()

    def get_scores(self) -> pd.Series:
        return self._get_scores_from_function(score_transit_stops, ["headway_string", "primary_mode"])

    def get_score_decay_function(self) -> Callable[[float], float]:
        return get_linear_decay_function(500)

    def get_folium_plot(self) -> folium.GeoJson:
        gtfs_popup = folium.GeoJsonPopup(
            fields=GTFS_STOPS_FIELDS_TO_DISPLAY,
            aliases=GTFS_ALIASES,
        )
        max_sqrt_score = np.percentile(np.sqrt(self.gdf["score"]), 98)
        gtfs_geojson = folium.GeoJson(
            self.gdf[[*GTFS_STOPS_FIELDS_TO_DISPLAY, self.gdf.geometry.name]],
            popup=gtfs_popup,
            marker=basic_circle_marker("orange"),
            style_function=lambda x: {
                "radius": max(1.5, np.sqrt(x["properties"]["score"])/max_sqrt_score * 5),
                "fillColor": MODE_COLOR_MAP[x["properties"]["primary_mode"]]
            },
        )
        return gtfs_geojson

    def _recursively_make_transitland_call(self, max_responses, initial_load_area_bounds, max_calls):
        # Call transitland recursively with a smaller bounding box until it doesn't give an error
        def make_transitland_call(max_responses, load_area_bounds, after = None, max_calls=None):
            if max_calls is not None and max_calls <= 0:
                raise RecursionError("Max Transitland calls exceeded")
            stringified_bounds = ",".join(map(lambda x: str(x), load_area_bounds))
            transitland_url = f"{self.transitland_url}?bbox={stringified_bounds}&limit={max_responses}&license_create_derived_product=exclude_no&license_redistribution_allowed=exclude_no&apikey={self.api_key}"
            if after is not None:
                transitland_url += f"&after={after}"
            print(f"INFO: Transitland URL: {transitland_url}")
            transitland_response = requests.get(transitland_url)
            transitland_response.raise_for_status()
            transitland_json = transitland_response.json()
            new_max_calls = None if max_calls is None else max_calls - 1
            if "meta" in transitland_json:
                additional_feeds, returned_max_calls = make_transitland_call(
                    max_responses,
                    load_area_bounds,
                    after=transitland_json["meta"]["after"],
                    max_calls=new_max_calls,
                )
                return transitland_json["feeds"] + additional_feeds, returned_max_calls
            return transitland_response.json()["feeds"], new_max_calls

        def recursively_make_transitland_call_help(max_responses, initial_load_area_bounds, max_calls):
            if max_calls == 0:
                raise RecursionError("Max Transitland calls exceeded")
            try:
                returned_feeds, _ = make_transitland_call(max_responses, initial_load_area_bounds)
                return returned_feeds, max_calls - 1
            except requests.exceptions.HTTPError as e:
                if e.response.status_code != 500:
                    raise(e)
                bounds_center = (
                    (initial_load_area_bounds[0] + initial_load_area_bounds[2]) / 2,
                    (initial_load_area_bounds[1] + initial_load_area_bounds[3]) / 2,
                )
                quadrant_one = (
                    bounds_center[0],
                    bounds_center[1],
                    initial_load_area_bounds[2],
                    initial_load_area_bounds[3],
                )
                quadrant_two = (
                    initial_load_area_bounds[0],
                    bounds_center[1],
                    bounds_center[0],
                    initial_load_area_bounds[3],
                )
                quadrant_three = (
                    initial_load_area_bounds[0], 
                    initial_load_area_bounds[1],
                    bounds_center[0], 
                    bounds_center[1],
                )
                quadrant_four = (
                    bounds_center[0],
                    initial_load_area_bounds[1],
                    initial_load_area_bounds[2],
                    bounds_center[1],
                )
                feeds = []
                current_max_calls = max_calls - 1
                for quadrant in (quadrant_one, quadrant_two, quadrant_three, quadrant_four):
                    returned_feeds, returned_max_calls = recursively_make_transitland_call_help(max_responses, quadrant, current_max_calls)
                    feeds.append(returned_feeds)
                    current_max_calls = returned_max_calls
                all_feeds_with_duplicates = np.concatenate(feeds)
                unique_feed_indices = np.unique(
                    [feed["onestop_id"] for feed in all_feeds_with_duplicates],
                    return_index = True
                )[1]
                output = all_feeds_with_duplicates[unique_feed_indices]
                return output, current_max_calls
        output, _ = recursively_make_transitland_call_help(max_responses, initial_load_area_bounds, max_calls)
        return output

