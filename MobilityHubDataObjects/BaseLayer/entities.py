from abc import ABC, abstractmethod
from typing import Iterable

import pandas as pd
import geopandas as gpd
from pygris.data import get_census

from .utils import split_county_fips
from .constants import GEOID_COLUMN


class BaseLayerMetric(ABC):
    df = pd.DataFrame()
    census_id_column = ""
    metric_column = ""
    name = ""
    _loaded = False

    def get_is_loaded(self):
        return self._loaded
    def _set_is_loaded(self):
        self._loaded = True

    @abstractmethod
    def load_data(
        self,
        county_fips: Iterable[str]
    ) -> None:
        pass

    def get_data_for_ids(self, ids: pd.Series) -> pd.DataFrame | pd.Series:
        return self.df.loc[ids].rename(self.name)
    
    def should_send_block_group_gdf(self) -> bool:
        return False
    def send_block_group_gdf(self, gdf: gpd.GeoDataFrame) -> None:
        raise NotImplementedError("This layer does not have a block group gdf configured")
    

class BaseLayerCensus(BaseLayerMetric, ABC):
    @property
    @abstractmethod
    def variable_dict(cls) -> dict[str, str]:
        pass

    def __init__(self):
        self.census_id_column = GEOID_COLUMN
    
    def load_data(self, county_fips: Iterable[str]):
        state_fips, county_fips = split_county_fips(county_fips)
        state = state_fips.iloc[0]
        data = get_census(
            dataset="2022/acs/acs5",
            variables=list(self.variable_dict.values()),
            params={
                "for": f"block group: *",
                "in": f"state: {state} county: {','.join(county_fips)}"
            },
            return_geoid = True,
            guess_dtypes = True,
        ).set_index(self.census_id_column)
        self.df = data
        self._set_is_loaded()
    
    @abstractmethod
    def get_data_for_ids(self, ids: pd.Series) -> pd.Series:
        pass