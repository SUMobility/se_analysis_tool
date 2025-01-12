from dataclasses import dataclass
import hashlib
from typing import Callable
import typing
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

from MobilityHubDataObjects.transitWrappers.constants import MODE_COLOR_MAP
from MobilityHubDataObjects.GTFSFeedWrapperLegacy import GTFSFeedWrapperLegacy
from MobilityHubDataObjects.scoreDecayFunctions import get_linear_decay_function
from MobilityHubDataObjects.scoreFunctions import get_score_constant_value, score_transit_stops
from MobilityHubDataObjects.transitWrappers import TransitNetwork
from MobilityHubDataObjects.transitWrappers.FeedWrapper import FeedWrapper
from MobilityHubDataObjects.transitWrappers.constants import ROUTE_TYPE_TO_ROUTE_DISPLAY_NAME_MAP
from MobilityHubDataObjects.utils import basic_circle_marker, download_file_with_playwright, download_file_with_requests, download_latest_feed_version_from_transitland, filter_two_corresponding_arrays, get_str_or_na, safe_is_na, transform_shapely_geometry, yes_no_to_bool
from MobilityHubDataObjects.constants import GEODESIC_CRS

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

@dataclass
class DownloadResponse:
    response_success: bool
    output_path: pathlib.Path | None
    sha1_hash: typing.Any

MAX_RESPONSES_PER_PAGE = 100
MAX_CHUNK_SIZE = 65536
MAX_CALLS = 100
MIN_TRIPS = 5

class GTFSDataObject(SpatialDataObject):
    df_feeds_metadata = None
    load_area = None
    gdf = gpd.GeoDataFrame()

    def __init__(
        self,
        local_crs: int,
        gtfs_cache_path: str | pathlib.Path,
        transitland_url: str,
        api_key_path: str,
        gtfs_override_feeds_path: None | str | pathlib.Path = None,
        download_transitland_first: bool = True,
        network_config: dict = {}
    ) -> None:
        self.local_crs = local_crs
        self.gtfs_cache_path = pathlib.Path(gtfs_cache_path).resolve()
        if gtfs_override_feeds_path is not None:
            self.gtfs_override_feeds_path = pathlib.Path(gtfs_override_feeds_path).resolve()
        else:
            self.gtfs_override_feeds_path = None
        self.transitland_url = transitland_url
        #TODO: add api calls to download gtfs files
        self.all_gtfs_paths = None
        self.transitland_last_queried = None
        with open(api_key_path) as f:
            self.api_key = f.read()
        self.download_transitland_first = download_transitland_first
        self.network_config = network_config

    async def load_data(
        self,
        load_area: (shapely.MultiPolygon | shapely.Polygon),
        load_area_crs: int
    ) -> None:
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
        network = TransitNetwork([], self.local_crs, config=self.network_config)
        for feed in transitland_feeds:
            feed_id = feed["onestop_id"]
            print(f"INFO: Processing {feed_id}")
            # Get the most recent currently valid feed
            current_feed_version = feed["feed_state"]["feed_version"]
            if not current_feed_version:
                df_feeds_metadata.loc[feed_id, "last_fetch_succeeded"] = False
                continue 
            # The current feed is already in the cache, so we may not need to download a new file
            cached_feed_metadata = df_feeds_metadata.loc[feed_id]
            cached_last_downloaded = dt.datetime.fromisoformat(cached_feed_metadata["last_fetched"])
            #cached_end_of_life = dt.datetime.fromisoformat(cached_feed_metadata["last_valid_date"])
            cached_fetch_status = cached_feed_metadata["last_fetch_succeeded"]
            assert not safe_is_na(cached_last_downloaded) and not safe_is_na(cached_fetch_status)
            # Download the feed and update the feed metadata
            feed_url = current_feed_version["url"]
            response = await self._download_feed(feed_id, feed_url, df_override_feeds)
            if not response.response_success:
                continue
            # Validate the hash, but do not fail (hashes will not match if transitland hasn't cached the feed recently)
            feed_output_path = response.output_path
            if (
                response.sha1_hash is not None 
                and response.sha1_hash.hexdigest() != current_feed_version["sha1"]
            ):
                print(
                    f"WARN: For {feed['onestop_id']}, the hash {response.sha1_hash.hexdigest()} does not match the provided hash from Transitland {current_feed_version['sha1']}"
                )
            
            feed_last_fetched = dt.datetime.now(tz=dt.timezone.utc)
            #feed_end_of_life_dt = dt.datetime.fromisoformat(df_current_feed_version["latest_calendar_date"])
            feed_attribution_url = get_str_or_na(feed["license"]["url"])
            feed_attribution_text = get_str_or_na(feed["license"]["attribution_text"])
            feed_attribution_instructions = get_str_or_na(feed["license"]["attribution_instructions"])
            feed_must_attribute = yes_no_to_bool(feed["license"]["use_without_attribution"])
            

            # Load the feed object
            print(f"Loading {feed_id}")
            feed_object = FeedWrapper(feed_output_path, feed_id, load_area, load_area_crs, MIN_TRIPS)
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

            # Add the feed to the network
            network.add_feed(feed_object)
        gdf_stop_locations = network.gdf_stops.copy()
        #df_route_summary = network.get_summary_routes_df()
        gdf_stop_locations["min_overlap_headway"] = network.get_headways_by_stop_overlap().groupby(level=0).min()
        gdf_stop_locations["total_frequency"] = network.get_frequencies_by_stop_overlap().groupby(level=0).max()
        gdf_stop_locations["transfer"] = network.get_transfer_status()
        gdf_stop_locations["mode"] = network.get_mode_classification()
        
        self.df_feeds_metadata = df_feeds_metadata
        self.gdf_stop_locations = gdf_stop_locations
        self._network = network
        # Save stops and feed metadata to file
        df_feeds_metadata.to_csv(feeds_metadata_path)
        gdf_stop_locations.to_file(stops_geometry_path)
        return network.get_headways_by_stop_overlap().groupby(level=0).min()

    def get_scores(self) -> pd.Series:
        return self._get_scores_from_function(score_transit_stops, ["headway_string", "primary_mode"])

    def get_score_decay_function(self) -> Callable[[float], float]:
        return get_linear_decay_function(500)

    def get_folium_plot(self) -> folium.GeoJson:
        gtfs_popup = folium.GeoJsonPopup(
            fields=GTFS_STOPS_FIELDS_TO_DISPLAY,
            aliases=GTFS_ALIASES,
        )
        gtfs_geojson = folium.GeoJson(
            self.gdf[[*GTFS_STOPS_FIELDS_TO_DISPLAY, self.gdf.geometry.name]],
            popup=gtfs_popup,
            marker=basic_circle_marker("orange"),
            style_function=lambda x: {
                "fillColor": MODE_COLOR_MAP[x["properties"]["mode"]]
            },
        )
        return gtfs_geojson

    async def _download_feed(self, feed_id, feed_url, df_override_feeds):
        feed_output_path = self.gtfs_cache_path / f"gtfs_{feed_id}.zip"
        #if feed_id in df_override_feeds.index:
        #    feed_output_path = self.gtfs_cache_path / df_override_feeds.loc[feed_id, "path"])
        # Download the feed
        try:
            sha1_hash = download_file_with_requests(feed_url, feed_output_path, MAX_CHUNK_SIZE)
        except requests.HTTPError:
            sha1_hash = None
        except requests.exceptions.MissingSchema:
            print(f"WARN: URL {feed_url} is invalid. Skipping")
            return DownloadResponse(False, None, None)
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
            return DownloadResponse(False, None, None)
        return DownloadResponse(True, feed_output_path, sha1_hash)

        

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

