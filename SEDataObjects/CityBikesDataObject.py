from typing import Any

import folium
import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from folium.features import GeoJson

from SEDataObjects import SpatialDataObject, constants
from SEDataObjects.utils import (
    basic_circle_marker,
    download_json_safely,
    filter_two_corresponding_arrays,
    transform_shapely_geometry,
)


COUNTRY_CODE_US = "US"

# Maximum reasonable capacity for one individual bike-share station.
# This removes malformed aggregate/network records such as 1,003,568 bikes.
MAX_REASONABLE_STATION_CAPACITY = 1_000

CITYBIKES_FIELDS = [
    "system_name",
    "system",
    "station_name",
    "capacity",
    "has_ebikes",
]

CITYBIKES_ALIASES = [
    "System Name",
    "Operator",
    "Station Name",
    "Capacity",
    "Has Ebikes?",
]


class CityBikesDataObject(SpatialDataObject):
    _gdf = gpd.GeoDataFrame
    name = "citybikes_bikeshare_docks"

    def __init__(self, citybikes_url: str) -> None:
        self.citybikes_url = citybikes_url.rstrip("/")

    def load_data(
        self,
        load_area: shapely.MultiPolygon | shapely.Polygon,
        load_area_crs: int,
    ) -> None:
        """
        Load CityBikes stations that fall within the requested load area.

        The CityBikes API returns a list of bikeshare networks. Each network
        must then be queried individually to retrieve its station records.
        """

        # Transform the map area into latitude/longitude because CityBikes
        # coordinates are geographic coordinates.
        load_area_geographic = transform_shapely_geometry(
            load_area_crs,
            constants.GEODESIC_CRS,
            load_area,
        )

        # Download the list of CityBikes networks.
        networks_url = f"{self.citybikes_url}/v2/networks"
        citybikes_feeds_json = download_json_safely(networks_url)

        if not isinstance(citybikes_feeds_json, dict):
            raise RuntimeError(
                f"Unexpected response from CityBikes networks endpoint: "
                f"{type(citybikes_feeds_json).__name__}"
            )

        networks = citybikes_feeds_json.get("networks", [])

        if not networks:
            self._gdf = self._empty_geodataframe()
            self._set_is_loaded()
            return

        df_citybikes_feeds = pd.DataFrame.from_records(networks)

        if df_citybikes_feeds.empty:
            self._gdf = self._empty_geodataframe()
            self._set_is_loaded()
            return

        # Keep only US networks. Some records may not have a valid location.
        df_citybikes_feeds["country"] = df_citybikes_feeds[
            "location"
        ].map(self._get_country)

        df_citybikes_feeds_us = df_citybikes_feeds.loc[
            df_citybikes_feeds["country"] == COUNTRY_CODE_US
        ].copy()

        if df_citybikes_feeds_us.empty:
            self._gdf = self._empty_geodataframe()
            self._set_is_loaded()
            return

        # Extract network coordinates safely.
        df_citybikes_feeds_us["latitude"] = df_citybikes_feeds_us[
            "location"
        ].map(self._get_latitude)

        df_citybikes_feeds_us["longitude"] = df_citybikes_feeds_us[
            "location"
        ].map(self._get_longitude)

        df_citybikes_feeds_us["latitude"] = pd.to_numeric(
            df_citybikes_feeds_us["latitude"],
            errors="coerce",
        )

        df_citybikes_feeds_us["longitude"] = pd.to_numeric(
            df_citybikes_feeds_us["longitude"],
            errors="coerce",
        )

        # Remove network records without usable coordinates.
        df_citybikes_feeds_us = df_citybikes_feeds_us.loc[
            df_citybikes_feeds_us["latitude"].between(-90, 90)
            & df_citybikes_feeds_us["longitude"].between(-180, 180)
        ].copy()

        if df_citybikes_feeds_us.empty:
            self._gdf = self._empty_geodataframe()
            self._set_is_loaded()
            return

        gdf_citybikes_feeds_us = gpd.GeoDataFrame(
            df_citybikes_feeds_us,
            geometry=gpd.points_from_xy(
                df_citybikes_feeds_us["longitude"],
                df_citybikes_feeds_us["latitude"],
            ),
            crs=constants.GEODESIC_CRS,
        )

        # IMPORTANT:
        # Both the network points and load_area_geographic are now in the
        # same geographic CRS.
        gdf_citybikes_feeds_in_load_area = (
            gdf_citybikes_feeds_us.loc[
                gdf_citybikes_feeds_us.intersects(load_area_geographic)
            ]
            .copy()
        )

        if gdf_citybikes_feeds_in_load_area.empty:
            self._gdf = self._empty_geodataframe()
            self._set_is_loaded()
            return

        # Download station records for each network.
        gdf_citybikes_feeds_in_load_area["stations"] = (
            gdf_citybikes_feeds_in_load_area["href"].map(
                self._download_feed
            )
        )

        # Drop networks whose feed failed or returned no station data.
        gdf_citybikes_feeds_in_load_area = (
            gdf_citybikes_feeds_in_load_area.loc[
                gdf_citybikes_feeds_in_load_area["stations"].apply(
                    lambda value: isinstance(value, list)
                )
            ]
            .copy()
        )

        if gdf_citybikes_feeds_in_load_area.empty:
            self._gdf = self._empty_geodataframe()
            self._set_is_loaded()
            return

        # Convert each station list into one row per station.
        df_citybikes_stations = (
            gdf_citybikes_feeds_in_load_area.explode(
                "stations",
                ignore_index=True,
            )
        )

        # Retain only actual station dictionaries.
        df_citybikes_stations = (
            df_citybikes_stations.loc[
                df_citybikes_stations["stations"].apply(
                    lambda value: isinstance(value, dict)
                )
            ]
            .copy()
        )

        if df_citybikes_stations.empty:
            self._gdf = self._empty_geodataframe()
            self._set_is_loaded()
            return

        # Extract station attributes.
        df_citybikes_stations["longitude"] = pd.to_numeric(
            df_citybikes_stations["stations"].map(
                lambda station: station.get("longitude")
            ),
            errors="coerce",
        )

        df_citybikes_stations["latitude"] = pd.to_numeric(
            df_citybikes_stations["stations"].map(
                lambda station: station.get("latitude")
            ),
            errors="coerce",
        )

        df_citybikes_stations["station_name"] = (
            df_citybikes_stations["stations"].map(
                lambda station: station.get("name")
            )
        )

        df_citybikes_stations["free_bikes"] = pd.to_numeric(
            df_citybikes_stations["stations"].map(
                lambda station: station.get("free_bikes")
            ),
            errors="coerce",
        )

        df_citybikes_stations["empty_slots"] = pd.to_numeric(
            df_citybikes_stations["stations"].map(
                lambda station: station.get("empty_slots")
            ),
            errors="coerce",
        )

        df_citybikes_stations["has_ebikes"] = (
            df_citybikes_stations["stations"].map(
                self._get_has_ebikes
            )
        )

        # Compute total station capacity.
        df_citybikes_stations["capacity"] = (
            df_citybikes_stations["empty_slots"].fillna(0)
            + df_citybikes_stations["free_bikes"].fillna(0)
        )

        # Remove records with invalid geographic coordinates.
        df_citybikes_stations = df_citybikes_stations.loc[
            df_citybikes_stations["latitude"].between(-90, 90)
            & df_citybikes_stations["longitude"].between(-180, 180)
        ].copy()

        # Remove records without a station name.
        #
        # Aggregate/network-level records commonly have city names or
        # malformed values rather than actual station names.
        df_citybikes_stations["station_name"] = (
            df_citybikes_stations["station_name"]
            .astype("string")
            .str.strip()
        )

        df_citybikes_stations = df_citybikes_stations.loc[
            df_citybikes_stations["station_name"].notna()
            & df_citybikes_stations["station_name"].ne("")
        ].copy()

        # Remove clearly invalid aggregate records.
        #
        # A station with a capacity of 1,003,568 is not a real individual
        # station. It is a malformed network-level record.
        df_citybikes_stations = df_citybikes_stations.loc[
            df_citybikes_stations["capacity"].le(
                MAX_REASONABLE_STATION_CAPACITY
            )
        ].copy()

        if df_citybikes_stations.empty:
            self._gdf = self._empty_geodataframe()
            self._set_is_loaded()
            return

        # Create point geometries in latitude/longitude.
        gdf_citybikes_stations = gpd.GeoDataFrame(
            df_citybikes_stations,
            geometry=gpd.points_from_xy(
                df_citybikes_stations["longitude"],
                df_citybikes_stations["latitude"],
            ),
            crs=constants.GEODESIC_CRS,
        )

        # Keep only stations inside the requested map area.
        gdf_citybikes_stations_to_save = (
            gdf_citybikes_stations.loc[
                gdf_citybikes_stations.intersects(load_area_geographic)
            ]
            .copy()
        )

        if gdf_citybikes_stations_to_save.empty:
            self._gdf = self._empty_geodataframe()
            self._set_is_loaded()
            return

        # The network's "name" field becomes system_name.
        if "name" in gdf_citybikes_stations_to_save.columns:
            gdf_citybikes_stations_to_save = (
                gdf_citybikes_stations_to_save.rename(
                    columns={"name": "system_name"}
                )
            )

        # Make sure all required output columns exist.
        for column in CITYBIKES_FIELDS:
            if column not in gdf_citybikes_stations_to_save.columns:
                gdf_citybikes_stations_to_save[column] = np.nan

        self._gdf = gpd.GeoDataFrame(
            gdf_citybikes_stations_to_save[
                [*CITYBIKES_FIELDS, "geometry"]
            ],
            geometry="geometry",
            crs=constants.GEODESIC_CRS,
        )

        self._set_is_loaded()

    def get_folium_plot(self) -> GeoJson:
        """
        Return a Folium GeoJSON layer for CityBikes stations.
        """

        fields, aliases = filter_two_corresponding_arrays(
            self._gdf.columns,
            CITYBIKES_FIELDS,
            CITYBIKES_ALIASES,
        )

        citybikes_popup = folium.GeoJsonPopup(
            fields=fields,
            aliases=aliases,
            localize=True,
        )

        return folium.GeoJson(
            self._gdf,
            popup=citybikes_popup,
            marker=basic_circle_marker("green"),
        )

    def _download_feed(self, feed_href: Any) -> list | np.ndarray:
        """
        Download one CityBikes network feed.

        Returns an empty list when the feed is unavailable or malformed.
        """

        if not isinstance(feed_href, str) or not feed_href.strip():
            return []

        feed_url = self._build_feed_url(feed_href)

        try:
            feed_json = download_json_safely(feed_url)
        except Exception as error:
            print(
                f"WARNING: Could not download CityBikes feed "
                f"{feed_url}: {error}"
            )
            return []

        if not isinstance(feed_json, dict):
            print(
                f"WARNING: CityBikes feed returned an unexpected response: "
                f"{feed_url}"
            )
            return []

        network = feed_json.get("network")

        if not isinstance(network, dict):
            print(
                f"WARNING: CityBikes feed has no valid network object: "
                f"{feed_url}"
            )
            return []

        stations = network.get("stations", [])

        if not isinstance(stations, list):
            print(
                f"WARNING: CityBikes feed has no valid station list: "
                f"{feed_url}"
            )
            return []

        print(
            f"Loaded {len(stations)} CityBikes stations from {feed_url}"
        )

        return stations

    def _build_feed_url(self, feed_href: str) -> str:
        """
        Build a CityBikes feed URL without duplicating slashes.
        """

        if feed_href.startswith("http://") or feed_href.startswith("https://"):
            return feed_href

        return f"{self.citybikes_url}/{feed_href.lstrip('/')}"

    @staticmethod
    def _get_country(location: Any) -> Any:
        if isinstance(location, dict):
            return location.get("country")
        return np.nan

    @staticmethod
    def _get_latitude(location: Any) -> Any:
        if isinstance(location, dict):
            return location.get("latitude")
        return np.nan

    @staticmethod
    def _get_longitude(location: Any) -> Any:
        if isinstance(location, dict):
            return location.get("longitude")
        return np.nan

    @staticmethod
    def _get_has_ebikes(station: Any) -> str:
        if not isinstance(station, dict):
            return "unknown"

        extra = station.get("extra")

        if not isinstance(extra, dict):
            return "unknown"

        has_ebikes = extra.get("has_ebikes")

        if has_ebikes is None:
            return "unknown"

        return str(has_ebikes)

    @staticmethod
    def _empty_geodataframe() -> gpd.GeoDataFrame:
        """
        Return an empty GeoDataFrame with the expected schema.
        """

        return gpd.GeoDataFrame(
            {
                field: pd.Series(dtype="object")
                for field in CITYBIKES_FIELDS
            },
            geometry=gpd.GeoSeries([], dtype="geometry"),
            crs=constants.GEODESIC_CRS,
        )