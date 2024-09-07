from abc import ABC, abstractmethod
import geopandas as gpd
import shapely


class APIDataObject(ABC):
    @abstractmethod
    def __init__(self, source: str, cache_path: str, api_key_path: str):
        self.source = source
        self.cache_path = cache_path
        self.api_key_path = api_key_path
        self._gdf_cache = gpd.GeoDataFrame
    @abstractmethod
    def load_data(self, load_area: (shapely.MultiPolygon | shapely.Polygon | None)):
        pass
    @abstractmethod
    def save_cache_to_file(self):
        pass
