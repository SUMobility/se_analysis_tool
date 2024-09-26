from abc import ABC, abstractmethod

import folium
import geopandas as gpd
import shapely


class DataObject(ABC):
    @abstractmethod
    def load_data(
        self,
        load_area: (shapely.MultiPolygon | shapely.Polygon),
        load_area_crs: int = 4326 
    ) -> None:
        pass

    def get_folium_plot(self) -> folium.GeoJson:
        pass
