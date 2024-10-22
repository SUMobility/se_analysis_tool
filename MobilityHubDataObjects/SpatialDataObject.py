from abc import ABC, abstractmethod

import folium
import geopandas as gpd
import numpy as np
import pandas as pd
import shapely


class SpatialDataObject(ABC):
    is_loaded = False
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

    def get_scores(self, score_function, score_fields) -> pd.Series:
        if type(score_fields) is list and len(score_fields) > 1:
            assert len(np.intersect1d(score_fields, self.gdf.columns)) == len(score_fields)
            return self.gdf.apply(score_function, axis=1)
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
