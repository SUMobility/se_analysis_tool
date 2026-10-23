from __future__ import annotations

import pathlib

import folium
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from SEDataObjects import SpatialDataObject
from SEDataObjects.utils import (
    basic_circle_marker,
    filter_two_corresponding_arrays,
)


FARS_FIELDS = [
    "ST_CASE",
    "STATENAME",
    "COUNTYNAME",
    "CITYNAME",
    "LATITUDE",
    "LONGITUD",
    "PERNOTMVIT",
    "PERMVIT",
    "PEDS",
    "FATALS",
    "FUNC_SYSNAME",
    "TYP_INTNAME",
    "LGT_CONDNAME",
    "WEATHERNAME",
    "YEAR",
]


FARS_ALIASES = [
    "Crash Case Number",
    "State Name",
    "County",
    "City",
    "Latitude",
    "Longitude",
    "Persons Not in Motor Vehicles",
    "Persons in Motor Vehicles",
    "Pedestrians",
    "Fatalities",
    "Road Type",
    "Intersection Type",
    "Lighting Condition",
    "Weather",
    "Year",
]


def fatality_marker() -> folium.Marker:
    """
    Create a warning-style marker for fatal crashes.
    """

    return folium.Marker(
        icon=folium.DivIcon(
            html="""
            <div
                title="Fatal crash involving a non-motorist"
                style="
                    width: 22px;
                    height: 22px;
                    border-radius: 50%;
                    background-color: #b30000;
                    border: 2px solid white;
                    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.5);
                    color: white;
                    font-size: 17px;
                    font-weight: bold;
                    line-height: 20px;
                    text-align: center;
                    font-family: Arial, sans-serif;
                "
            >!</div>
            """,
            icon_size=(26, 26),
            icon_anchor=(13, 13),
        )
    )


class FARSDataObject(SpatialDataObject):
    """
    Load FARS crash locations from a CSV file.

    The default filter retains crashes where PERNOTMVIT > 0.

    Note:
        PERNOTMVIT identifies crashes involving at least one
        non-motorist. It does not identify pedestrians exclusively.
    """

    _gdf = gpd.GeoDataFrame
    name = "fars_nonmotorist_crashes"

    def __init__(
        self,
        csv_path: str | pathlib.Path,
        filter_nonmotorist: bool = True,
    ) -> None:
        self.csv_path = pathlib.Path(csv_path)
        self.filter_nonmotorist = filter_nonmotorist

    def load_data(
        self,
        load_area,
        load_area_crs,
    ) -> None:
        """
        Load FARS crash points within load_area.

        The resulting GeoDataFrame uses EPSG:4326 because FARS
        latitude/longitude coordinates are geographic coordinates.
        """

        if not self.csv_path.exists():
            raise FileNotFoundError(
                f"FARS CSV was not found: {self.csv_path}"
            )

        print(f"Loading FARS data from {self.csv_path}")

        fars_df = pd.read_csv(
            self.csv_path,
            low_memory=False,
            encoding="utf-8-sig",
        )

        # Normalize column names.
        fars_df.columns = [
            str(column)
            .replace("\ufeff", "")
            .strip()
            .upper()
        for column in fars_df.columns
        ]

        # Normalize common alternate names.
        fars_df = fars_df.rename(
            columns={
                "LONGITUDE": "LONGITUD",
                "LON": "LONGITUD",
                "LONG": "LONGITUD",
                "LAT": "LATITUDE",
                "CASE_NUMBER": "ST_CASE",
                "CASE": "ST_CASE",
            }
        )

        required_columns = [
            "LATITUDE",
            "LONGITUD",
            "PERNOTMVIT",
        ]

        missing_columns = [
            column
            for column in required_columns
            if column not in fars_df.columns
        ]

        if missing_columns:
            raise KeyError(
                "The FARS CSV is missing required columns: "
                f"{missing_columns}. "
                f"Available columns: {fars_df.columns.tolist()}"
            )

        # Convert required values to numeric.
        for column in [
            "LATITUDE",
            "LONGITUD",
            "PERNOTMVIT",
        ]:
            fars_df[column] = pd.to_numeric(
                fars_df[column],
                errors="coerce",
            )

        # Retain crashes involving at least one non-motorist.
        if self.filter_nonmotorist:
            fars_df = fars_df.loc[
                fars_df["PERNOTMVIT"] > 0
            ].copy()

        # Remove invalid coordinate rows.
        fars_df = fars_df.loc[
            fars_df["LATITUDE"].between(-90, 90)
            & fars_df["LONGITUD"].between(-180, 180)
        ].copy()

        if fars_df.empty:
            print(
                "No FARS non-motorist crashes remained after filtering."
            )

            self._gdf = gpd.GeoDataFrame(
                columns=[
                    column
                    for column in FARS_FIELDS
                    if column != "geometry"
                ]
                + ["geometry"],
                geometry="geometry",
                crs="EPSG:4326",
            )

            self._set_is_loaded()
            return

        # Keep only known fields that exist in this CSV.
        selected_fields = [
            column
            for column in FARS_FIELDS
            if column in fars_df.columns
        ]

        fars_df = fars_df[selected_fields].copy()

        geometry = [
            Point(longitude, latitude)
            for longitude, latitude in zip(
                fars_df["LONGITUD"],
                fars_df["LATITUDE"],
            )
        ]

        fars_gdf = gpd.GeoDataFrame(
            fars_df,
            geometry=geometry,
            crs="EPSG:4326",
        )

        # Convert the requested map area to geographic coordinates.
        load_area_geographic = (
            gpd.GeoSeries(
                [load_area],
                crs=load_area_crs,
            )
            .to_crs(epsg=4326)
            .iloc[0]
        )

        # Keep only crash points inside the requested map area.
        fars_gdf = fars_gdf.loc[
            fars_gdf.geometry.within(load_area_geographic)
        ].copy()

        # Ensure every expected popup field exists.
        for column in FARS_FIELDS:
            if column not in fars_gdf.columns:
                fars_gdf[column] = pd.NA

        self._gdf = fars_gdf[
            [
                column
                for column in FARS_FIELDS
                if column in fars_gdf.columns
            ]
            + ["geometry"]
        ].copy()

        self._gdf = gpd.GeoDataFrame(
            self._gdf,
            geometry="geometry",
            crs="EPSG:4326",
        )

        print(
            f"Loaded {len(self._gdf)} FARS non-motorist crashes."
        )

        self._set_is_loaded()

    def get_folium_plot(self) -> folium.GeoJson:
        """
        Return FARS crashes as a Folium point layer.
        """

        fields, aliases = filter_two_corresponding_arrays(
            self._gdf.columns,
            FARS_FIELDS,
            FARS_ALIASES,
        )

        popup = folium.GeoJsonPopup(
            fields=fields,
            aliases=aliases,
            localize=True,
            labels=True,
        )

        tooltip_fields = [
            field
            for field in [
                "ST_CASE",
                "PERNOTMVIT",
                "PEDS",
                "FATALS",
                "CITYNAME",
                "YEAR",
            ]
            if field in self._gdf.columns
        ]

        tooltip_aliases = [
            FARS_ALIASES[
                FARS_FIELDS.index(field)
            ]
            for field in tooltip_fields
        ]

        tooltip = folium.GeoJsonTooltip(
            fields=tooltip_fields,
            aliases=tooltip_aliases,
            localize=True,
            sticky=False,
            labels=True,
        )

        return folium.GeoJson(
            self._gdf,
            name="FARS Non-Motorist Crashes",
            popup=popup,
            tooltip=tooltip,
            marker=fatality_marker(),
            style_function=lambda feature: {
                "color": "#8b0000",
                "fillColor": "#d73027",
                "weight": 1,
                "fillOpacity": 0.85,
            },
        )