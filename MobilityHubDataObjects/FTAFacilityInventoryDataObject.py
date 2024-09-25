import pathlib

import numpy as np
import pandas as pd
import geopandas as gpd
import shapely
from pyproj import CRS
import folium

from MobilityHubDataObjects.utils import basic_circle_marker

from .DataObject import DataObject


class FTAFacilityInventoryDataObject(DataObject):
    data_object = gpd.GeoDataFrame
    def __init__(
        self,
        path: (str | pathlib.Path),
        columns: [str] = ("NTD ID", "Agency Name", "Facility Type", "Facility Name", "Notes"),
        column_filter: (dict[str, [str]] | None) = None,
        sheet_name: (str | None) = None,
        x_column: str = "Longitude",
        y_column: str = "Latitude",
        address_columns: [str] = ("Street Address", "City", "State", "Zip Code"),
    ):
        self.path = pathlib.Path(path)
        self.columns = tuple(columns)
        self.column_filter = column_filter
        self.sheet_name = sheet_name
        self.x_column = x_column
        self.y_column = y_column
        self.address_columns = tuple(address_columns)

    def load_data(
        self,
        load_area: (shapely.MultiPolygon | shapely.Polygon)
    ) -> None:
        if not self.sheet_name:
            gdf_inventory = pd.read_excel(self.path)
        else:
            gdf_inventory = pd.read_excel(self.path, sheet_name=self.sheet_name).loc[:, self.columns]
        if self.column_filter is not None:
            for column in self.column_filter.keys():
                gdf_inventory = gdf_inventory.loc[
                    gdf_inventory[column].isin(self.column_filter[column])
                ].copy()
        #TODO: add geocoding for entries that don't have lat/lon
        gdf_inventory = gpd.GeoDataFrame(
            gdf_inventory,
            geometry=gpd.points_from_xy(
                gdf_inventory[self.x_column],
                gdf_inventory[self.y_column],
                crs="EPSG:4326"
            )
        ).loc[:, self.columns + ("geometry",)]
        if load_area is not None:
            self.data_object = gdf_inventory.loc[gdf_inventory.within(load_area)].copy()
        else:
            self.data_object = gdf_inventory.copy()

    def get_folium_plot(self) -> folium.GeoJson:
        fta_popup = folium.GeoJsonPopup(
            fields=list(np.intersect1d(
                ["NTD ID", "Agency Name", "Facility Type", "Facility Name", "Notes"],
                self.data_object.index
            ))
        )
        fta_geojson = folium.GeoJson(
            self.data_object,
            marker=basic_circle_marker("light_blue"),
            popup=fta_popup
        )
        return fta_geojson



