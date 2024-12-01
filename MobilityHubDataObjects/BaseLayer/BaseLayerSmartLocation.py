from typing import Iterable
import geopandas as gpd
import numpy as np
import pandas as pd

from MobilityHubDataObjects.constants import GEODESIC_CRS

from .constants import SMART_LOCATION_COLUMN, SMART_LOCATION_NAME
from .utils import split_county_fips
from .entities import BaseLayerMetric


class BaseLayerSmartLocation(BaseLayerMetric):
    gdf_bgs = None
    def __init__(self, smartlocation_path: str, local_crs: int) -> None:
        self.smartlocation_path = smartlocation_path
        self.local_crs = local_crs
    
    def load_data(
        self,
        county_fips: Iterable[str]
    ):
        # Check that a block group dataframe for the regoin has been passed
        if self.gdf_bgs is None:
            raise RuntimeError("Need to pass block group GDF")
        state_fips, county_only_fips = split_county_fips(county_fips)
        
        # Load the block groups that overlap with the given county fips codes
        gdf_bgs_2021_filtered = self.gdf_bgs.loc[
            (self.gdf_bgs["STATEFP"].isin(state_fips)) & (self.gdf_bgs["COUNTYFP"].isin(county_only_fips))
        ].to_crs(
            self.local_crs
        )
        # Get the smart location gdf. Note that the Smart Location geometry is 2018 Block Groups
        gdf_smartlocation = gpd.read_file(self.smartlocation_path, mask=gdf_bgs_2021_filtered).to_crs(self.local_crs)
        gdf_smartlocation = gdf_smartlocation.loc[
            gdf_smartlocation.intersects(gdf_bgs_2021_filtered.unary_union)
        ]
        # Overlay the 2021 and 2018 block groups and get the area that the 2021 block groups overlap the 2018 block groups
        gdf_bgs_2021_projected = gdf_bgs_2021_filtered.to_crs(self.local_crs)
        gdf_bgs_2021_projected["original_geoid"] = gdf_bgs_2021_projected.index
        gdf_bgs_2021_projected["original_area"] = gdf_bgs_2021_projected.area
        gdf_bgs_overlapped = gdf_bgs_2021_projected.overlay(gdf_smartlocation, how="intersection")
        # Remove very small overlaps (TODO: delete this, shouldn't be necessary)
        # gdf_bgs_overlapped = gdf_bgs_overlapped.loc[gdf_bgs_overlapped.area > MIN_FRAGMENT_AREA]
        # Round values that are gvery close to 1 or 0 to avoid floating point errors and to discount very small overlaps
        gdf_bgs_overlapped["area_proportion"] = gdf_bgs_overlapped.area / gdf_bgs_overlapped["original_area"]
        gdf_bgs_overlapped.loc[gdf_bgs_overlapped["area_proportion"] < 0.01, "area_proportion"] = 0
        gdf_bgs_overlapped.loc[gdf_bgs_overlapped["area_proportion"] > 0.99, "area_proportion"] = 1
        # Infer the value for the relevant value of the 2021 block groups, based on the proportion of overlap with each of the 2018 block groups
        gdf_bgs_overlapped["weighted_value"] = gdf_bgs_overlapped[SMART_LOCATION_COLUMN] * gdf_bgs_overlapped["area_proportion"]
        gdf_bgs_2021_projected[SMART_LOCATION_NAME] = gdf_bgs_overlapped.groupby("original_geoid")["weighted_value"].sum()
        gdf_bgs_2021_projected.loc[gdf_bgs_2021_projected[SMART_LOCATION_NAME] < 0, SMART_LOCATION_NAME] = np.nan
        # Save the results
        self.gdf = gdf_bgs_2021_projected.to_crs(GEODESIC_CRS).copy()
        self._set_is_loaded()
    
    def get_data_for_ids(self, ids: pd.Series) -> pd.Series:
        return self.gdf.loc[ids, SMART_LOCATION_NAME]
    
    def should_send_block_group_gdf(self) -> bool:
        return True
    
    def send_block_group_gdf(self, gdf: gpd.GeoDataFrame) -> None:
        self.gdf_bgs = gdf