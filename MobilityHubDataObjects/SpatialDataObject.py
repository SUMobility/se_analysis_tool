from abc import ABC, abstractmethod

import folium
import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from typing import Callable


class SpatialDataObject(ABC):
    _loaded = False
    gdf = gpd.GeoDataFrame

    @abstractmethod
    def load_data(
        self,
        load_area: (shapely.MultiPolygon | shapely.Polygon),
        load_area_crs: int
    ) -> None:
        pass

    @abstractmethod
    def get_folium_plot(self) -> folium.GeoJson:
        pass

    @abstractmethod
    def get_scores(self) -> pd.Series:
        pass

    @abstractmethod
    def get_score_decay_function(self) -> Callable[[float], float]:
        pass

    def get_scores_with_geometry(self) -> gpd.GeoDataFrame:
        return gpd.GeoDataFrame({"score": self.get_scores()}, geometry=self.gdf.geometry, index=self.gdf.index)

    def _get_scores_from_function(self, score_function, score_fields) -> pd.Series:
        if type(score_fields) is list and len(score_fields) > 1:
            assert len(np.intersect1d(score_fields, self.gdf.columns)) == len(score_fields)
            return self.gdf.apply(score_function, axis=1)
        elif type(score_fields) is list and len(score_fields) == 0:
            return pd.Series(score_function(), index=self.gdf.index)
        elif type(score_fields) is list:
            assert score_fields[0] in self.gdf.columns
            return self.gdf[score_fields[0]].map(score_function)
        elif type(score_fields) is str:
            assert score_fields in self.gdf.columns
            return self.gdf[score_fields].map(score_function)
        elif type(score_fields) is not list and type(score_fields) is not str:
            raise TypeError("Score fields is not a list or string")
        else:
            raise KeyError("Not all elements of score_fields are valid columns")
        
    def get_is_loaded(self):
        return self._loaded
    def _set_is_loaded(self):
        self._loaded = True
