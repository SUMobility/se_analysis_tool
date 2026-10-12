from __future__ import annotations

import pathlib
from typing import Any, Iterable
from urllib.parse import urljoin

import folium
import geopandas as gpd
import numpy as np
import pandas as pd
import requests
import shapely

from SEDataObjects import SpatialDataObject, constants
from SEDataObjects.utils import (
    basic_circle_marker,
    filter_two_corresponding_arrays,
)


GBFS_FIELDS = [
    "system_name",
    "system_id",
    "station_id",
    "station_name",
    "capacity",
    "num_bikes_available",
    "num_docks_available",
    "has_ebikes",
    "is_renting",
    "is_returning",
    "last_reported",
]

GBFS_ALIASES = [
    "System Name",
    "System ID",
    "Station ID",
    "Station Name",
    "Capacity",
    "Bikes Available",
    "Docks Available",
    "Has E-bikes?",
    "Renting",
    "Returning",
    "Last Reported",
]


class GBFSDataObject(SpatialDataObject):
    """
    Loads station-based bikeshare stations from GBFS feeds.

    Parameters
    ----------
    gbfs_urls:
        One GBFS discovery URL or an iterable of discovery URLs.

        Examples:
            https://example.com/gbfs.json
            https://example.com/gbfs/en/gbfs.json
    """

    _gdf = gpd.GeoDataFrame
    name = "gbfs_bikeshare_stations"

    def __init__(
        self,
        gbfs_urls: str | pathlib.Path | Iterable[str | pathlib.Path],
        request_timeout: int = 30,
        preferred_language: str = "en",
    ) -> None:
        if isinstance(gbfs_urls, (str, pathlib.Path)):
            gbfs_urls = [gbfs_urls]

        self.gbfs_urls = [
            str(url).strip()
            for url in gbfs_urls
            if str(url).strip()
        ]

        self.request_timeout = request_timeout
        self.preferred_language = preferred_language

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "SEAnalysisTool/1.0 "
                    "GBFS station map client"
                )
            }
        )

    def load_data(
        self,
        load_area: shapely.MultiPolygon | shapely.Polygon,
        load_area_crs: int,
    ) -> None:
        """
        Load GBFS stations within load_area.
        """

        if load_area is None or load_area.is_empty:
            self._gdf = self._empty_geodataframe()
            self._set_is_loaded()
            return

        # GBFS station coordinates are longitude/latitude.
        load_area_geographic = (
            gpd.GeoSeries(
                [load_area],
                crs=load_area_crs,
            )
            .to_crs(constants.GEODESIC_CRS)
            .iloc[0]
        )

        all_station_frames: list[pd.DataFrame] = []

        for discovery_url in self.gbfs_urls:
            try:
                discovery = self._get_json(discovery_url)
                feed_urls = self._find_feed_urls(
                    discovery,
                    discovery_url,
                )

                if "station_information" not in feed_urls:
                    print(
                        "WARNING: GBFS feed does not provide "
                        f"station_information: {discovery_url}"
                    )
                    continue

                station_information = self._get_json(
                    feed_urls["station_information"]
                )

                station_status = None

                if "station_status" in feed_urls:
                    try:
                        station_status = self._get_json(
                            feed_urls["station_status"]
                        )
                    except Exception as error:
                        print(
                            "WARNING: Could not load station_status "
                            f"from {feed_urls['station_status']}: {error}"
                        )

                system_information = None

                if "system_information" in feed_urls:
                    try:
                        system_information = self._get_json(
                            feed_urls["system_information"]
                        )
                    except Exception as error:
                        print(
                            "WARNING: Could not load system_information: "
                            f"{error}"
                        )

                station_df = self._build_station_dataframe(
                    station_information=station_information,
                    station_status=station_status,
                    system_information=system_information,
                    discovery_url=discovery_url,
                )

                if not station_df.empty:
                    all_station_frames.append(station_df)

            except Exception as error:
                print(
                    f"WARNING: Could not load GBFS feed "
                    f"{discovery_url}: {error}"
                )

        if not all_station_frames:
            self._gdf = self._empty_geodataframe()
            self._set_is_loaded()
            return

        df_stations = pd.concat(
            all_station_frames,
            ignore_index=True,
        )

        # Ensure numeric coordinates.
        df_stations["latitude"] = pd.to_numeric(
            df_stations["latitude"],
            errors="coerce",
        )

        df_stations["longitude"] = pd.to_numeric(
            df_stations["longitude"],
            errors="coerce",
        )

        df_stations = df_stations.loc[
            df_stations["latitude"].between(-90, 90)
            & df_stations["longitude"].between(-180, 180)
        ].copy()

        if df_stations.empty:
            self._gdf = self._empty_geodataframe()
            self._set_is_loaded()
            return

        station_gdf = gpd.GeoDataFrame(
            df_stations,
            geometry=gpd.points_from_xy(
                df_stations["longitude"],
                df_stations["latitude"],
            ),
            crs=constants.GEODESIC_CRS,
        )

        # Keep stations inside or on the boundary of the map area.
        station_gdf = station_gdf.loc[
            station_gdf.intersects(load_area_geographic)
        ].copy()

        if station_gdf.empty:
            self._gdf = self._empty_geodataframe()
            self._set_is_loaded()
            return

        for field in GBFS_FIELDS:
            if field not in station_gdf.columns:
                station_gdf[field] = np.nan

        self._gdf = gpd.GeoDataFrame(
            station_gdf[
                [*GBFS_FIELDS, "geometry"]
            ],
            geometry="geometry",
            crs=constants.GEODESIC_CRS,
        )

        print(
            f"Loaded {len(self._gdf)} GBFS bikeshare stations."
        )

        self._set_is_loaded()

    def get_folium_plot(self) -> folium.GeoJson:
        """
        Return GBFS stations as a Folium GeoJSON point layer.
        """

        if self._gdf is None or self._gdf.empty:
            return folium.GeoJson(
                self._empty_geodataframe(),
                name="GBFS Bikeshare Stations",
            )

        fields, aliases = filter_two_corresponding_arrays(
            self._gdf.columns,
            GBFS_FIELDS,
            GBFS_ALIASES,
        )

        popup = folium.GeoJsonPopup(
            fields=fields,
            aliases=aliases,
            localize=True,
        )

        tooltip = folium.GeoJsonTooltip(
            fields=[
                field
                for field in [
                    "system_name",
                    "station_name",
                    "num_bikes_available",
                    "num_docks_available",
                ]
                if field in self._gdf.columns
            ],
            aliases=[
                alias
                for field, alias in zip(
                    GBFS_FIELDS,
                    GBFS_ALIASES,
                )
                if field in [
                    "system_name",
                    "station_name",
                    "num_bikes_available",
                    "num_docks_available",
                ]
            ],
            localize=True,
            sticky=False,
        )

        return folium.GeoJson(
            self._gdf,
            popup=popup,
            tooltip=tooltip,
            marker=basic_circle_marker("green"),
        )

    def _build_station_dataframe(
        self,
        station_information: dict[str, Any],
        station_status: dict[str, Any] | None,
        system_information: dict[str, Any] | None,
        discovery_url: str,
    ) -> pd.DataFrame:
        """
        Build one row per station and merge station status.
        """

        station_records = self._extract_records(
            station_information,
            "stations",
        )

        if not station_records:
            return pd.DataFrame()

        info_df = pd.DataFrame.from_records(station_records)

        if "station_id" not in info_df.columns:
            print(
                "WARNING: station_information has no station_id: "
                f"{discovery_url}"
            )
            return pd.DataFrame()

        # GBFS v3 localized station names may be arrays of objects.
        if "name" in info_df.columns:
            info_df["station_name"] = info_df["name"].map(
                self._localized_text
            )
        else:
            info_df["station_name"] = "Unnamed station"

        if "lat" not in info_df.columns:
            info_df["lat"] = np.nan

        if "lon" not in info_df.columns:
            info_df["lon"] = np.nan

        info_df["latitude"] = pd.to_numeric(
            info_df["lat"],
            errors="coerce",
        )

        info_df["longitude"] = pd.to_numeric(
            info_df["lon"],
            errors="coerce",
        )

        status_df = pd.DataFrame()

        if station_status is not None:
            status_records = self._extract_records(
                station_status,
                "stations",
            )

            if status_records:
                status_df = pd.DataFrame.from_records(
                    status_records
                )

                if "station_id" in status_df.columns:
                    status_df = status_df.drop_duplicates(
                        subset=["station_id"],
                        keep="last",
                    )

        if not status_df.empty:
            info_df = info_df.merge(
                status_df,
                on="station_id",
                how="left",
                suffixes=("", "_status"),
            )

        # GBFS v2 uses num_bikes_available.
        # GBFS v3 uses num_vehicles_available.
        if (
            "num_bikes_available" not in info_df.columns
            and "num_vehicles_available" in info_df.columns
        ):
            info_df["num_bikes_available"] = (
                info_df["num_vehicles_available"]
            )

        if "num_bikes_available" not in info_df.columns:
            info_df["num_bikes_available"] = np.nan

        if "num_docks_available" not in info_df.columns:
            info_df["num_docks_available"] = np.nan

        # Prefer explicit station capacity when present.
        if "capacity" not in info_df.columns:
            info_df["capacity"] = np.nan

        info_df["capacity"] = pd.to_numeric(
            info_df["capacity"],
            errors="coerce",
        )

        # If capacity is missing, calculate it from bikes + docks.
        calculated_capacity = (
            pd.to_numeric(
                info_df["num_bikes_available"],
                errors="coerce",
            )
            + pd.to_numeric(
                info_df["num_docks_available"],
                errors="coerce",
            )
        )

        info_df["capacity"] = info_df["capacity"].fillna(
            calculated_capacity
        )

        if "is_renting" not in info_df.columns:
            info_df["is_renting"] = np.nan

        if "is_returning" not in info_df.columns:
            info_df["is_returning"] = np.nan

        if "last_reported" not in info_df.columns:
            info_df["last_reported"] = np.nan

        info_df["has_ebikes"] = info_df.apply(
            self._get_has_ebikes,
            axis=1,
        )

        system_name = self._get_system_name(
            system_information,
            fallback=discovery_url,
        )

        info_df["system_name"] = system_name
        info_df["system_id"] = self._get_system_id(
            system_information
        )
        info_df["gbfs_source_url"] = discovery_url

        return info_df

    def _find_feed_urls(
        self,
        discovery: dict[str, Any],
        discovery_url: str,
    ) -> dict[str, str]:
        """
        Find feed URLs from GBFS v2 or v3 discovery JSON.
        """

        feed_urls: dict[str, str] = {}

        data = discovery.get("data", {})

        # GBFS v2 commonly uses:
        # data -> feeds -> [{"name": ..., "url": ...}]
        if isinstance(data, dict):
            feeds = data.get("feeds")

            if isinstance(feeds, list):
                self._add_feed_records(
                    feeds,
                    feed_urls,
                    discovery_url,
                )

            # GBFS v3 can organize feeds by language:
            # data -> en -> feeds -> [...]
            for language_data in data.values():
                if not isinstance(language_data, dict):
                    continue

                language_feeds = language_data.get("feeds")

                if isinstance(language_feeds, list):
                    self._add_feed_records(
                        language_feeds,
                        feed_urls,
                        discovery_url,
                    )

        # Some feeds may expose feeds directly at the top level.
        top_level_feeds = discovery.get("feeds")

        if isinstance(top_level_feeds, list):
            self._add_feed_records(
                top_level_feeds,
                feed_urls,
                discovery_url,
            )

        return feed_urls

    def _add_feed_records(
        self,
        feeds: list[Any],
        feed_urls: dict[str, str],
        discovery_url: str,
    ) -> None:
        for feed in feeds:
            if not isinstance(feed, dict):
                continue

            feed_name = feed.get("name")
            feed_url = feed.get("url")

            if not isinstance(feed_name, str):
                continue

            if not isinstance(feed_url, str):
                continue

            normalized_name = feed_name.lower().strip()

            # Support v2/v3 aliases.
            aliases = {
                "station_info": "station_information",
                "station_information": "station_information",
                "station_status": "station_status",
                "system_information": "system_information",
                "free_bike_status": "vehicle_status",
                "vehicle_status": "vehicle_status",
            }

            normalized_name = aliases.get(
                normalized_name,
                normalized_name,
            )

            if normalized_name not in {
                "station_information",
                "station_status",
                "system_information",
            }:
                continue

            absolute_url = urljoin(
                discovery_url,
                feed_url,
            )

            if (
                normalized_name not in feed_urls
                or self._prefer_url(
                    absolute_url,
                    feed_urls[normalized_name],
                )
            ):
                feed_urls[normalized_name] = absolute_url

    def _prefer_url(
        self,
        candidate_url: str,
        current_url: str,
    ) -> bool:
        """
        Prefer a URL containing the requested language when possible.
        """

        preferred_language = self.preferred_language.lower()

        candidate_lower = candidate_url.lower()
        current_lower = current_url.lower()

        candidate_is_preferred = preferred_language in candidate_lower
        current_is_preferred = preferred_language in current_lower

        return candidate_is_preferred and not current_is_preferred

    def _get_json(self, url: str) -> dict[str, Any]:
        response = self.session.get(
            url,
            timeout=self.request_timeout,
        )
        response.raise_for_status()

        data = response.json()

        if not isinstance(data, dict):
            raise ValueError(
                f"Expected a JSON object from {url}"
            )

        return data

    @staticmethod
    def _extract_records(
        document: dict[str, Any],
        key: str,
    ) -> list[dict[str, Any]]:
        data = document.get("data", {})

        if not isinstance(data, dict):
            return []

        records = data.get(key, [])

        if not isinstance(records, list):
            return []

        return [
            record
            for record in records
            if isinstance(record, dict)
        ]

    def _get_system_name(
        self,
        system_information: dict[str, Any] | None,
        fallback: str,
    ) -> str:
        if not system_information:
            return fallback

        data = system_information.get("data", {})

        if not isinstance(data, dict):
            return fallback

        name = data.get("name")

        if isinstance(name, str):
            return name

        localized_name = self._localized_text(name)

        if localized_name:
            return localized_name

        return fallback

    @staticmethod
    def _get_system_id(
        system_information: dict[str, Any] | None,
    ) -> str | None:
        if not system_information:
            return None

        data = system_information.get("data", {})

        if not isinstance(data, dict):
            return None

        system_id = data.get("system_id")

        if system_id is None:
            return None

        return str(system_id)

    def _get_has_ebikes(
        self,
        row: pd.Series,
    ) -> str | bool:
        """
        Read e-bike information when supplied by the feed.

        Different operators expose this in different optional fields, so
        unknown is returned when the feed does not publish it.
        """

        for column in [
            "has_ebikes",
            "ebikes_available",
            "num_ebikes_available",
        ]:
            if column not in row.index:
                continue

            value = row.get(column)

            if pd.isna(value):
                continue

            if column == "num_ebikes_available":
                try:
                    return int(value) > 0
                except (TypeError, ValueError):
                    continue

            return value

        vehicle_types = row.get("vehicle_types_available")

        if isinstance(vehicle_types, list):
            for vehicle_type in vehicle_types:
                if not isinstance(vehicle_type, dict):
                    continue

                vehicle_type_id = str(
                    vehicle_type.get("vehicle_type_id", "")
                ).lower()

                if "electric" in vehicle_type_id or "ebike" in vehicle_type_id:
                    return True

        return "unknown"

    def _localized_text(self, value: Any) -> str:
        """
        Convert GBFS v2/v3 text values to a display string.

        v2 commonly uses a string.
        v3 may use an array such as:
        [{"text": "Station Name", "language": "en"}].
        """

        if isinstance(value, str):
            return value

        if isinstance(value, list):
            localized_values = [
                item
                for item in value
                if isinstance(item, dict)
                and isinstance(item.get("text"), str)
            ]

            if not localized_values:
                return ""

            for item in localized_values:
                if item.get("language") == self.preferred_language:
                    return item["text"]

            return localized_values[0]["text"]

        if isinstance(value, dict):
            text = value.get("text")

            if isinstance(text, str):
                return text

        return ""

    @staticmethod
    def _empty_geodataframe() -> gpd.GeoDataFrame:
        return gpd.GeoDataFrame(
            {
                field: pd.Series(dtype="object")
                for field in GBFS_FIELDS
            },
            geometry=gpd.GeoSeries([], dtype="geometry"),
            crs=constants.GEODESIC_CRS,
        )