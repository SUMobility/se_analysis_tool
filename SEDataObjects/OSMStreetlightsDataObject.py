from __future__ import annotations

import pathlib
from typing import Any

import folium
import geopandas as gpd
import numpy as np
import osmnx as ox
import pandas as pd
import requests
import shapely

from osmnx import _errors as OsmnxExceptions

from SEDataObjects import SpatialDataObject, constants
from SEDataObjects.utils import (
    basic_circle_marker,
    filter_two_corresponding_arrays,
)


STREETLIGHT_FIELDS = [
    "osm_id",
    "streetlight_type",
    "lamp_type",
    "lamp_model",
    "light_source",
    "support",
    "lit",
    "operator",
    "source",
]

STREETLIGHT_ALIASES = [
    "OSM ID",
    "Streetlight Type",
    "Lamp Type",
    "Lamp Model",
    "Light Source",
    "Support",
    "Lit",
    "Operator",
    "Source",
]


class OSMStreetlightsDataObject(SpatialDataObject):
    """
    Load streetlights from OpenStreetMap using OSMnx.

    Primary OSM tag:
        highway=street_lamp
    """

    _gdf = gpd.GeoDataFrame
    name = "osm_streetlights"

    def __init__(
        self,
        osm_cache_folder: str | pathlib.Path,
        request_timeout: int = 180,
    ) -> None:
        self.osm_cache_folder = pathlib.Path(osm_cache_folder)
        self.request_timeout = request_timeout

    def load_data(
        self,
        load_area: shapely.MultiPolygon | shapely.Polygon,
        load_area_crs: int,
    ) -> None:
        """
        Query OSM streetlights within the supplied map area.

        Output geometries are points in GEODESIC_CRS, normally EPSG:4326.
        """

        if load_area is None or load_area.is_empty:
            self._gdf = self._empty_geodataframe()
            self._set_is_loaded()
            return

        # Configure OSMnx cache and timeout.
        old_cache_folder = ox.settings.cache_folder
        old_timeout = ox.settings.requests_timeout

        # OSMnx versions differ in how the Overpass URL is exposed.
        old_overpass_url = getattr(
            ox.settings,
            "overpass_url",
            None,
        )

        try:
            ox.settings.cache_folder = self.osm_cache_folder
            ox.settings.use_cache = True
            ox.settings.requests_timeout = self.request_timeout

            # Convert the map area to geographic coordinates because OSMnx
            # expects polygon coordinates in longitude/latitude.
            load_area_geographic = (
                gpd.GeoSeries(
                    [load_area],
                    crs=load_area_crs,
                )
                .to_crs(constants.GEODESIC_CRS)
                .iloc[0]
            )

            streetlight_tags = {
                "highway": "street_lamp",
            }

            streetlights = self._query_osm_with_retries(
                polygon=load_area_geographic,
                tags=streetlight_tags,
            )

            if streetlights is None or streetlights.empty:
                print("No OSM streetlights found.")
                self._gdf = self._empty_geodataframe()
                self._set_is_loaded()
                return

            streetlights = streetlights.copy()

            # OSMnx returns an index that may be a MultiIndex containing
            # element type and OSM ID. Preserve a usable ID field.
            streetlights["osm_id"] = [
                self._extract_osm_id(index)
                for index in streetlights.index
            ]

            # Keep valid geometries.
            streetlights = streetlights.loc[
                streetlights.geometry.notna()
                & ~streetlights.geometry.is_empty
            ].copy()

            if streetlights.empty:
                self._gdf = self._empty_geodataframe()
                self._set_is_loaded()
                return

            # Most street_lamp features are points. Convert any non-point
            # geometry to a representative point so the map layer is a
            # point layer.
            streetlights["geometry"] = streetlights.geometry.map(
                self._to_point_geometry
            )

            streetlights = streetlights.loc[
                streetlights.geometry.notna()
                & ~streetlights.geometry.is_empty
            ].copy()

            # Normalize optional OSM attributes.
            source_columns = [
                "highway",
                "street_lamp:type",
                "lamp_type",
                "lamp_model",
                "light_source",
                "support",
                "lit",
                "operator",
                "source",
            ]

            for column in source_columns:
                if column not in streetlights.columns:
                    streetlights[column] = np.nan

            streetlights["streetlight_type"] = streetlights[
                "street_lamp:type"
            ]

            streetlights["streetlight_type"] = (
                streetlights["streetlight_type"]
                .fillna(streetlights["highway"])
            )

            streetlights = streetlights.rename(
                columns={
                    "lamp_type": "lamp_type",
                    "lamp_model": "lamp_model",
                    "light_source": "light_source",
                    "support": "support",
                    "lit": "lit",
                    "operator": "operator",
                    "source": "source",
                }
            )

            for field in STREETLIGHT_FIELDS:
                if field not in streetlights.columns:
                    streetlights[field] = np.nan

            self._gdf = gpd.GeoDataFrame(
                streetlights[
                    [*STREETLIGHT_FIELDS, "geometry"]
                ],
                geometry="geometry",
                crs=constants.GEODESIC_CRS,
            )

            print(
                f"Loaded {len(self._gdf)} OSM streetlights."
            )

            self._set_is_loaded()

        finally:
            # Restore global OSMnx settings.
            ox.settings.cache_folder = old_cache_folder
            ox.settings.requests_timeout = old_timeout

            if old_overpass_url is not None:
                ox.settings.overpass_url = old_overpass_url

    def get_folium_plot(self) -> folium.GeoJson:
        """
        Return streetlights as a Folium point layer.
        """

        if self._gdf is None or self._gdf.empty:
            return folium.GeoJson(
                self._empty_geodataframe(),
                name="OSM Streetlights",
            )

        fields, aliases = filter_two_corresponding_arrays(
            self._gdf.columns,
            STREETLIGHT_FIELDS,
            STREETLIGHT_ALIASES,
        )

        popup = folium.GeoJsonPopup(
            fields=fields,
            aliases=aliases,
            localize=True,
        )

        tooltip_fields = [
            field
            for field in [
                "streetlight_type",
                "lamp_type",
                "light_source",
                "lit",
            ]
            if field in self._gdf.columns
        ]

        tooltip_aliases = [
            STREETLIGHT_ALIASES[
                STREETLIGHT_FIELDS.index(field)
            ]
            for field in tooltip_fields
        ]

        tooltip = folium.GeoJsonTooltip(
            fields=tooltip_fields,
            aliases=tooltip_aliases,
            localize=True,
            sticky=False,
        )

        return folium.GeoJson(
            self._gdf,
            popup=popup,
            tooltip=tooltip,
            marker=basic_circle_marker("#ffcc00"),
        )

    def _query_osm_with_retries(
        self,
        polygon: shapely.Polygon | shapely.MultiPolygon,
        tags: dict[str, Any],
        attempts_per_endpoint: int = 2,
    ) -> gpd.GeoDataFrame | None:
        """
        Query Overpass with retries and endpoint fallback.
        """

        endpoints = [
            "https://overpass.kumi.systems/api",
            "https://overpass-api.de/api",
        ]

        last_error: Exception | None = None

        for endpoint in endpoints:
            if hasattr(ox.settings, "overpass_url"):
                ox.settings.overpass_url = endpoint

            for attempt in range(attempts_per_endpoint):
                try:
                    print(
                        f"Querying OSM streetlights using {endpoint}; "
                        f"attempt {attempt + 1}/"
                        f"{attempts_per_endpoint}"
                    )

                    result = ox.features_from_polygon(
                        polygon=polygon,
                        tags=tags,
                    )

                    if result is None:
                        return None

                    return result

                except (
                    requests.exceptions.ConnectionError,
                    requests.exceptions.ConnectTimeout,
                    requests.exceptions.ReadTimeout,
                    requests.exceptions.ChunkedEncodingError,
                    requests.exceptions.RequestException,
                    ConnectionError,
                    TimeoutError,
                    OSError,
                ) as error:
                    last_error = error

                    print(
                        f"WARNING: Streetlight Overpass request failed: "
                        f"{error}"
                    )

                except OsmnxExceptions.InsufficientResponseError as error:
                    last_error = error

                    print(
                        "WARNING: Overpass returned an insufficient "
                        f"streetlight response: {error}"
                    )

                except Exception as error:
                    last_error = error

                    print(
                        f"WARNING: Unexpected streetlight query error: "
                        f"{error}"
                    )

                if attempt < attempts_per_endpoint - 1:
                    wait_seconds = 3 * (attempt + 1)
                    print(
                        f"Retrying in {wait_seconds} seconds..."
                    )

                    import time

                    time.sleep(wait_seconds)

        print(
            "WARNING: All Overpass streetlight queries failed."
        )
        print(f"Last error: {last_error}")

        return None

    @staticmethod
    def _extract_osm_id(index: Any) -> str:
        """
        Extract a usable OSM identifier from an OSMnx index.
        """

        if isinstance(index, tuple):
            # Typical OSMnx MultiIndex:
            # (element_type, osmid)
            if len(index) >= 2:
                return str(index[1])

        return str(index)

    @staticmethod
    def _to_point_geometry(
        geometry: shapely.Geometry,
    ) -> shapely.Point | None:
        """
        Convert OSM geometries to points for point-map display.
        """

        if geometry is None or geometry.is_empty:
            return None

        if geometry.geom_type == "Point":
            return geometry

        return geometry.representative_point()

    @staticmethod
    def _empty_geodataframe() -> gpd.GeoDataFrame:
        return gpd.GeoDataFrame(
            {
                field: pd.Series(dtype="object")
                for field in STREETLIGHT_FIELDS
            },
            geometry=gpd.GeoSeries([], dtype="geometry"),
            crs=constants.GEODESIC_CRS,
        )