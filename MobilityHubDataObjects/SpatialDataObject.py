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
        
    def get_is_loaded(self):
        return self._loaded
    def _set_is_loaded(self):
        self._loaded = True
