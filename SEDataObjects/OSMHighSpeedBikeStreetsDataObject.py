from __future__ import annotations

import re

import folium
import geopandas as gpd
import pandas as pd
from folium.features import GeoJson

from SEDataObjects.OSMBikeStreetsDataObject import (
    OSMBikeStreetsDataObject,
)


HIGH_SPEED_BIKE_FIELDS = [
    "cycleway",
    "highway",
    "maxspeed",
    "speed_mph",
    "paint_only",
]


HIGH_SPEED_BIKE_ALIASES = [
    "Cycleway Type",
    "Road Type",
    "OSM Speed Limit",
    "Speed Limit (mph)",
    "Paint Only?",
]


class OSMHighSpeedBikeStreetsDataObject(
    OSMBikeStreetsDataObject
):
    """
    OSM bike lanes that are:

    1. Identified as paint-only/unprotected by the parent object.
    2. Located on roads with maxspeed >= the configured threshold.
    """

    _gdf = gpd.GeoDataFrame
    name = "osm_high_speed_unprotected_bike_lanes"

    def __init__(
        self,
        cache_path,
        max_speed_mph: float = 45.0,
        max_distance_from_reference=None,
        reference=None,
        local_crs=None,
    ):
        super().__init__(
            cache_path=cache_path,
            max_distance_from_reference=(
                max_distance_from_reference
            ),
            reference=reference,
            local_crs=local_crs,
        )

        self.max_speed_mph = float(max_speed_mph)

    def load_data(
        self,
        load_area,
        load_area_crs,
    ) -> None:
        """
        Load the existing OSM bike-lane classification and retain only
        paint-only lanes on roads at or above the speed threshold.
        """

        super().load_data(
            load_area,
            load_area_crs,
        )

        if self._gdf is None or self._gdf.empty:
            self._set_empty_gdf()
            self._set_is_loaded()
            return

        # Only retain lanes already classified as unprotected.
        self._gdf = self._gdf.loc[
            self._gdf["paint_only"].eq(True)
        ].copy()

        if self._gdf.empty:
            self._set_empty_gdf()
            self._set_is_loaded()
            return

        # Convert maxspeed to numeric miles per hour.
        self._gdf["speed_mph"] = self._gdf[
            "maxspeed"
        ].map(self._parse_speed_mph)

        # Retain only roads at or above the threshold.
        self._gdf = self._gdf.loc[
            self._gdf["speed_mph"].ge(
                self.max_speed_mph
            )
        ].copy()

        self._gdf = self._gdf.reset_index(
            drop=True
        )

        print(
            f"Loaded {len(self._gdf)} unprotected bike-lane "
            f"segments on roads at or above "
            f"{self.max_speed_mph:g} mph."
        )

        self._set_is_loaded()

    def get_folium_plot(self) -> GeoJson:
        """
        Return high-speed unprotected bike lanes as a Folium line layer.
        """

        if self._gdf is None or self._gdf.empty:
            raise RuntimeError(
                "High-speed bike-lane data is empty or has not "
                "been loaded."
            )

        popup = folium.GeoJsonPopup(
            fields=HIGH_SPEED_BIKE_FIELDS,
            aliases=HIGH_SPEED_BIKE_ALIASES,
            localize=True,
            labels=True,
        )

        tooltip = folium.GeoJsonTooltip(
            fields=[
                "highway",
                "maxspeed",
                "speed_mph",
            ],
            aliases=[
                "Road Type",
                "OSM Speed Limit",
                "Speed Limit (mph)",
            ],
            localize=True,
            sticky=False,
            labels=True,
        )

        return folium.GeoJson(
            data=self._gdf.to_json(),
            name=(
                "Unprotected Bike Lanes on Roads "
                f"{self.max_speed_mph:g}+ mph"
            ),
            popup=popup,
            tooltip=tooltip,
            style_function=lambda feature: {
                "color": "#ff1493",
                "weight": 6,
                "opacity": 0.95,
            },
            highlight_function=lambda feature: {
                "color": "#ffff00",
                "weight": 9,
                "opacity": 1.0,
            },
        )

    def _set_empty_gdf(self) -> None:
        self._gdf = gpd.GeoDataFrame(
            columns=HIGH_SPEED_BIKE_FIELDS
            + ["geometry"],
            geometry="geometry",
            crs="EPSG:4326",
        )

    @staticmethod
    def _parse_speed_mph(value) -> float | None:
        """
        Convert an OSM maxspeed value to mph.

        Bare values such as 45 are treated as mph, which is generally
        appropriate for U.S. OSM data.
        """

        if value is None or pd.isna(value):
            return None

        if isinstance(value, (list, tuple, set)):
            values = list(value)
        else:
            values = str(value).split(";")

        parsed_speeds = []

        for item in values:
            text = str(item).strip().lower()

            if not text:
                continue

            match = re.search(
                r"[-+]?\d+(?:\.\d+)?",
                text,
            )

            if match is None:
                continue

            speed = float(match.group(0))

            if any(
                unit in text
                for unit in [
                    "km/h",
                    "kmh",
                    "kph",
                ]
            ):
                speed *= 0.621371

            # Explicit mph, mi/h, and bare values are treated as mph.
            parsed_speeds.append(speed)

        if not parsed_speeds:
            return None

        # For values such as "35;45", retain the highest listed speed.
        return max(parsed_speeds)