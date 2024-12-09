import time
from typing import Iterable
import geopandas as gpd
import numpy as np
import pandas as pd
from MobilityHubDataObjects.BaseLayer.constants import SMART_LOCATION_COLUMNS
from MobilityHubDataObjects.constants import GEODESIC_CRS
from .utils import split_county_fips


class SmartLocationWrapper:
    loaded_county_fips = []
    def __init__(self, smartlocation_path: str, local_crs: int) -> None:
        self.smartlocation_path = smartlocation_path
        self.local_crs = local_crs
    
    def load_data(
        self,
        gdf_bgs_current: gpd.GeoDataFrame,
        county_fips: Iterable[str]
    ):
        # Check that a block group dataframe for the region has been passed
        if gdf_bgs_current is None:
            raise RuntimeError("Need to pass block group GDF")
        state_fips, county_only_fips = split_county_fips(county_fips)
        
        # Load the block groups that overlap with the given county fips codes
        gdf_bgs_current_filtered = gdf_bgs_current.loc[
            (gdf_bgs_current["STATEFP"].isin(state_fips)) & (gdf_bgs_current["COUNTYFP"].isin(county_only_fips))
        ].to_crs(
            self.local_crs
        )
        # Get the smart location gdf. Note that the Smart Location geometry is 2018 Block Groups
        gdf_smartlocation = gpd.read_file(self.smartlocation_path, mask=gdf_bgs_current_filtered).to_crs(self.local_crs)
        gdf_smartlocation = gdf_smartlocation.loc[
            gdf_smartlocation.intersects(gdf_bgs_current_filtered.unary_union)
        ]
        # Overlay the current and smart location block groups and get the area that the 2021 block groups overlap the 2018 block groups
        gdf_bgs_current_projected = gdf_bgs_current_filtered.to_crs(self.local_crs)
        gdf_bgs_current_projected["original_geoid"] = gdf_bgs_current_projected.index
        gdf_bgs_current_projected["original_area"] = gdf_bgs_current_projected.area
        gdf_bgs_overlapped = gdf_bgs_current_projected.overlay(gdf_smartlocation, how="intersection")
        # Round values that are gvery close to 1 or 0 to avoid floating point errors and to discount very small overlaps
        gdf_bgs_overlapped["area_proportion"] = gdf_bgs_overlapped.area / gdf_bgs_overlapped["original_area"]
        gdf_bgs_overlapped.loc[gdf_bgs_overlapped["area_proportion"] < 0.01, "area_proportion"] = 0
        gdf_bgs_overlapped.loc[gdf_bgs_overlapped["area_proportion"] > 0.99, "area_proportion"] = 1
        # Infer the value for the relevant value of the 2021 block groups, based on the proportion of overlap with each of the 2018 block groups
        df_weighted_values = pd.concat([
            gdf_bgs_overlapped[SMART_LOCATION_COLUMNS].multiply(gdf_bgs_overlapped["area_proportion"], axis="index"),
            gdf_bgs_overlapped["original_geoid"],
        ], axis=1)
        gdf_bgs_current_projected[SMART_LOCATION_COLUMNS] = df_weighted_values.groupby("original_geoid")[SMART_LOCATION_COLUMNS].sum()
        gdf_bgs_current_projected[SMART_LOCATION_COLUMNS] = gdf_bgs_current_projected[SMART_LOCATION_COLUMNS].map(
            lambda x: np.nan if x < 0 else x
        )
        # Save the results
        self.gdf = gdf_bgs_current_projected.to_crs(GEODESIC_CRS).copy()
        self._set_is_loaded(county_fips)

    def get_is_loaded(self, county_fips: Iterable[str]) -> bool:
        for i in county_fips:
            if i not in self.loaded_county_fips:
                return False
            
        return True
    
    def _set_is_loaded(self, county_fips: Iterable[str]) -> None:
        self.loaded_county_fips = county_fips