from abc import ABC, abstractmethod

import folium
import geopandas as gpd
import shapely


class DataObject(ABC):
    @abstractmethod
    def load_data(
        self,
        load_area: [shapely.MultiPolygon | shapely.Polygon | None]
    ) -> None:
        pass

    def get_folium_plot(self) -> folium.GeoJson:
        pass
