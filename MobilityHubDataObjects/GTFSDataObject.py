import fiona
import folium
import numpy as np
import requests
from shapely import MultiPolygon, Polygon
import shapely
from MobilityHubDataObjects import DataObject
import datetime as dt
import pandas as pd
import geopandas as gpd
import hashlib
import pathlib
import subprocess

from MobilityHubDataObjects.GTFSFeedWrapper import GTFSFeedWrapper
from MobilityHubDataObjects.utils import basic_circle_marker, filter_two_corresponding_arrays, get_str_or_na, safe_is_na, transform_shapely_geometry, yes_no_to_bool
from MobilityHubDataObjects.constants import GEODESIC_CRS

class GTFSDataObject(DataObject):

    df_feeds_metadata = None
    load_area = None
    gdf_all_frequent_stops = gpd.GeoDataFrame()
    data_loaded = False

    def __init__(
        self,
        gtfs_cache_path: str | pathlib.Path,
        transitland_url: str,
        max_transitland_cache_life: dt.timedelta,
        time_start: dt.time,
        time_end: dt.time,
        min_headway: int, 
        api_key_path: str
    ) -> None:
        self.gtfs_cache_path = pathlib.Path(gtfs_cache_path).resolve()
        self.transitland_url = transitland_url
        self.time_start = time_start
        self.time_end = time_end
        self.min_headway = min_headway
        #TODO: add api calls to download gtfs files
        self.all_gtfs_paths = None
        self.max_transitland_cache_life = max_transitland_cache_life
        self.transitland_last_queried = None
        self.api_key_path = api_key_path

    def load_data(self, load_area: MultiPolygon | Polygon | None, load_area_crs: int = 4326) -> None:
        MAX_RESPONSES_PER_PAGE = 100
        MAX_CHUNK_SIZE = 65536
        def score_stop(headway_dict):
            if safe_is_na(headway_dict):
                return np.nan
            score = 0
            for headway in headway_dict.values():
                # weird fugly sigmoid just as a demo
                score += -10 * (1 / (1 + np.e ** (-(headway - 17)/5))) + 10.3229
            return score
        load_area_transformed = transform_shapely_geometry(load_area_crs, GEODESIC_CRS, load_area)
        transitland_json = {}
        # Query Transitland
        #TODO: needs to loop until we are sure each file is downloaded
        load_area_bounds = ",".join(map(lambda x: str(x), load_area_transformed.bounds))
        with open(self.api_key_path) as f:
            api_key_path = f.read()
        transitland_url = f"{self.transitland_url}?bbox={load_area_bounds}&limit={MAX_RESPONSES_PER_PAGE}&license_create_derived_product=exclude_no&license_redistribution_allowed=exclude_no&apikey={api_key_path}"
        transitland_response = requests.get(transitland_url)
        if transitland_response.status_code != 200:
            raise RuntimeError(f"TRANSITLAND API did not load with code {transitland_response.status_code}")
        else:
            transitland_json = transitland_response.json()
        df_feeds_metadata = pd.DataFrame
        feeds_columns = [
                "name",
                "agency_url"
                "url",
                "raw_feed_path",
                "processed_file_path",
                "last_fetched",
                "last_valid_date",
                "attribution_url",
                "attribution_text",
                "attribution_instructions",
                "attribution_must_attribute",
                "last_fetch_succeeded",
            ]
        feeds_metadata_path = self.gtfs_cache_path / "feeds.csv"
        stops_geometry_path = self.gtfs_cache_path / "processed_stops.geojson"
        try:
            df_feeds_metadata = pd.read_csv(
                feeds_metadata_path,
                index_col=0
            )
        except FileNotFoundError:
            df_feeds_metadata = pd.DataFrame(
                columns=feeds_columns,
            )
        try:
            gdf_cached_frequent_stops = gpd.read_file(stops_geometry_path)
        except fiona.errors.DriverError:
            gdf_cached_frequent_stops = gpd.GeoDataFrame(
                columns=["agency_name", "agency_id"]
            )
        frequent_stops_gdf_list = []
        processed_agency_ids = []
        for feed in transitland_json["feeds"]:
            feed_id = feed["onestop_id"]
            print(f"Got {feed_id}")
            # Get the most recent currently valid feed
            df_feed_versions = pd.DataFrame(feed["feed_versions"])
            df_feed_versions["date_fetched_dt"] = pd.to_datetime(df_feed_versions["fetched_at"])
            df_feed_versions["min_date_dt"] = pd.to_datetime(df_feed_versions["earliest_calendar_date"])
            df_feed_versions_relevant = df_feed_versions[df_feed_versions["min_date_dt"] <= dt.datetime.today()]
            #TODO: need to load stops from cache
            # Get feed metadata from the cache, if existent
            newest_relevant_feed_version = df_feed_versions.loc[df_feed_versions_relevant["date_fetched_dt"].idxmax()]
            download_new_file = True
            if feed_id in df_feeds_metadata.index and df_feeds_metadata.at[feed_id, "last_fetch_succeeded"]:
                # TODO: figure out if any of these are redundant 
                # The current feed is already in the cache, so we may not need to download a new file
                cached_feed_metadata = df_feeds_metadata.loc[feed_id]
                cached_last_downloaded = dt.datetime.fromisoformat(cached_feed_metadata["last_fetched"])
                cached_end_of_life = dt.datetime.fromisoformat(cached_feed_metadata["last_valid_date"])
                cached_fetch_status = cached_feed_metadata["last_fetch_succeeded"]
                assert not safe_is_na(cached_last_downloaded) and not safe_is_na(cached_end_of_life) and not safe_is_na(cached_fetch_status)
                if (
                    ((dt.datetime.now(tz=dt.timezone.utc) - cached_last_downloaded) <= self.max_transitland_cache_life)
                    and (cached_end_of_life < dt.datetime.today())
                ):
                    download_new_file = False
            if download_new_file:
                # Download the feed and update the feed metadata
                feed_url = newest_relevant_feed_version.loc["url"]
                feed_output_path = self.gtfs_cache_path / f"GTFS_{feed['onestop_id']}.zip"

                # Download the feed
                sha1_hash = hashlib.new("sha1")
                try:
                    with requests.get(feed_url, stream=True) as r:
                        print(f"downloading {feed['onestop_id']}")
                        try:
                            r.raise_for_status()
                            with open(feed_output_path, "wb") as f:
                                for chunk in r.iter_content(chunk_size=MAX_CHUNK_SIZE): 
                                    if chunk:
                                        f.write(chunk)
                                        sha1_hash.update(chunk)
                        except requests.HTTPError as e:
                            if r.status_code == 403:
                                # try downloading with curl instead, sometimes that fixes it...
                                # Would be better to use pycurl, but that won't import on my system
                                # TODO: need to only do this on a unix system
                                curl_command = f"curl -o {feed_output_path.resolve()} {feed_url}"
                                print(f"WARN: For {feed['onestop_id']}, the following error was triggered:")
                                print(e)
                                print(f"Trying to download {feed_url} with curl instead:")
                                subprocess.call(curl_command, shell=True) #TODO: internal screaming
                                try:
                                    # Attempt to open the downloaded feed as text - this should fail if the object is actually a feed
                                    with open(feed_output_path, "rb") as f:
                                        downloaded = f.read()
                                        try:
                                            if "ACCESS DENIED" in downloaded.decode("utf-8").upper():
                                                print(
                                                    f"WARN: Curl Download still refused for {feed_id}"
                                                )
                                            else:
                                                print(
                                                    f"WARN: The url at {feed_url} for {feed_id} responded with the following text rather than a feed"
                                                )
                                                print(downloaded.decode("utf-8"))
                                            df_feeds_metadata.loc[feed_id, "last_fetch_succeeded"] = False
                                            continue
                                        except UnicodeDecodeError:
                                            # This means that the file isn't text, so it likely is a valid feed
                                            print("Curl Download successful")
                                except FileNotFoundError:
                                    print("WARN: Curl download did not succeed")
                                    df_feeds_metadata.loc[feed_id, "last_fetch_succeeded"] = False
                                    continue
                            else:
                                print(f"Download for {feed_id} failed with error {e}")
                                df_feeds_metadata.loc[feed_id, "last_fetch_succeeded"] = False
                                continue
                except Exception as e:
                    print(f"Connection to {feed_url} for {feed_id} has the following error:")
                    print(e)
                    df_feeds_metadata.loc[feed_id, "last_fetch_succeeded"] = False
                    continue
                if sha1_hash.hexdigest() != newest_relevant_feed_version["sha1"]:
                    print(
                        f"WARN: For {feed['onestop_id']}, the hash {sha1_hash.hexdigest()} does not match {newest_relevant_feed_version['sha1']}"
                    )
                feed_last_fetched = dt.datetime.now(tz=dt.timezone.utc)
                feed_end_of_life_dt = dt.datetime.fromisoformat(newest_relevant_feed_version["latest_calendar_date"])
                feed_attribution_url = get_str_or_na(feed["license"]["url"])
                feed_attribution_text = get_str_or_na(feed["license"]["attribution_text"])
                feed_attribution_instructions = get_str_or_na(feed["license"]["attribution_instructions"])
                feed_must_attribute = yes_no_to_bool(feed["license"]["use_without_attribution"])
                #TODO: figure out feed object to get agency name and url and run feedutils functions without needing to load a new feed each time
                # Process frequent stops
                try:
                    feed_object = GTFSFeedWrapper(feed_output_path)
                except Exception as e:
                    print(f"The feed for {feed_id} downloaded successfully, but processing it gave the following fatal error:")
                    print(str(e))
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
                    "last_valid_date": feed_end_of_life_dt,
                    "attribution_url": feed_attribution_url,
                    "attribution_text": feed_attribution_text,
                    "attribution_instructions": feed_attribution_instructions,
                    "attribution_must_attribute": feed_must_attribute,
                    "last_fetch_succeeded": True,
                }

                # Get stop frequencies
                print("Processing stops - this takes a while")
                df_feed_stops_with_headway = None
                try:
                    df_feed_stops_with_headway = feed_object.get_stops_with_headways(
                        time_start=self.time_start,
                        time_end=self.time_end,
                        percentile=80,
                        trip_cutoff=5
                    )
                except Exception as e:
                    print(f"WARN: Could not process feed for {feed['onestop_id']}. Error below")
                    print(e)
                if df_feed_stops_with_headway is not None:
                    df_feed_stops_with_headway["min_headway"] = df_feed_stops_with_headway["headway"].map(
                        lambda x: np.nan if safe_is_na(x) else min(x.values())
                    )
                    df_feed_stops_with_headway["pretty_printed_headway"] = df_feed_stops_with_headway["headway"].map(
                        feed_object.get_pretty_printed_headway
                    )
                    df_feed_stops_with_headway["score"] = df_feed_stops_with_headway["headway"].map(score_stop)
                    df_frequent_stops = df_feed_stops_with_headway.loc[df_feed_stops_with_headway["min_headway"] <= self.min_headway]
                    gdf_frequent_stops = gpd.GeoDataFrame(
                        df_frequent_stops,
                        geometry=gpd.points_from_xy(df_frequent_stops["stop_lon"], df_frequent_stops["stop_lat"]),
                    )
                    if len(gdf_frequent_stops) > 0:
                        print(gdf_frequent_stops.head())
                        gdf_frequent_stops.loc[:, "agency_name"] = feed_name
                        gdf_frequent_stops.loc[:, "agency_id"] = feed_id
                        gdf_frequent_stops.crs = GEODESIC_CRS
                        gdf_frequent_stops_in_area = gdf_frequent_stops.loc[gdf_frequent_stops.within(load_area_transformed)]
                        
                        frequent_stops_gdf_list.append(
                            gdf_frequent_stops_in_area
                        )
                    processed_agency_ids.append(feed_id)
                

        
        # Merge newly downloaded and cached stops
        if len(frequent_stops_gdf_list) > 0:
            gdf_downloaded_frequent_stops = pd.concat(frequent_stops_gdf_list)
            gdf_cached_frequent_stops_to_keep = gpd.GeoDataFrame(columns=gdf_downloaded_frequent_stops.columns)
            if len(gdf_cached_frequent_stops) > 0:
                gdf_cached_frequent_stops_to_keep = gdf_cached_frequent_stops.loc[
                    ~gdf_cached_frequent_stops["agency_id"].isin(processed_agency_ids)
                ]
            assert (
                np.intersect1d(
                    gdf_downloaded_frequent_stops["agency_id"].unique(),
                    gdf_cached_frequent_stops_to_keep["agency_id"].unique(),
                ).size == 0
            )
            self.gdf_all_frequent_stops = pd.concat(
                [gdf_downloaded_frequent_stops.drop("headway", axis=1), gdf_cached_frequent_stops_to_keep]
            )
            # Save result to a file
            self.gdf_all_frequent_stops.to_file(stops_geometry_path)
        else:
            self.gdf_all_frequent_stops = gdf_cached_frequent_stops
        self.df_feeds_metadata = df_feeds_metadata
        # Save stops and feed metadata to file
        df_feeds_metadata.to_csv(feeds_metadata_path)
        self.data_loaded = True

    def get_folium_plot(self) -> folium.GeoJson:
        assert self.data_loaded
        intended_fields = ["agency_id", "agency_name", "stop_id", "stop_name", "pretty_printed_headway", "score"]
        intended_aliases = ["Agency ID", "Agency Name", "Stop ID", "Stop Name", "Headway by route", "Score"]
        fields, aliases = filter_two_corresponding_arrays(
            self.gdf_all_frequent_stops.columns,
            intended_fields,
            intended_aliases,
        )
        gtfs_popup = folium.GeoJsonPopup(
            fields=fields,
            alias=aliases,
        )
        gtfs_geojson = folium.GeoJson(
            self.gdf_all_frequent_stops,
            popup=gtfs_popup,
            marker=basic_circle_marker("dark_blue", radius=2.5),
            style_function = lambda x: {
                "radius": x["properties"]["score"]/10 * 5
            }
        )
        return gtfs_geojson