import folium
import shapely
from shapely.geometry import MultiPolygon as MultiPolygon, Polygon as Polygon

from MobilityHubDataObjects.utils import transform_shapely_geometry
from .DataObject import DataObject
import geopandas as gpd
import math
import numpy as np

class EJScreenDataObject(DataObject):
    data_object = gpd.GeoDataFrame
    def __init__(self, ejscreen_path):
        self.path = ejscreen_path
    
    def load_data(
            self,
            load_area: (shapely.MultiPolygon | shapely.Polygon | None),
            load_area_crs: int = 4326,
        ) -> None:
        gdf_ejscreen = gpd.read_file(self.path)[["PTRAF", "P_PTRAF", "geometry"]]
        self.data_object = gdf_ejscreen.loc[
            gdf_ejscreen.intersects(transform_shapely_geometry(load_area_crs, gdf_ejscreen.crs, load_area))
        ].copy() #TODO: maybe like shrink the block groups slightly and use within instead, since using intersect selects too many and using just within selects too few

    def get_folium_plot(self) -> folium.GeoJson:
        color_map = {
            0: "green",
            1: "green",
            2: "green",
            3: "green",
            4: "green",
            5: "green",
            6: "yellow",
            7: "yellow",
            9: "yellow",
            8: "red",
            9: "purple",
            10: "purple"
        }
        df_to_render = self.data_object.copy()
        df_to_render["color"] = df_to_render["P_PTRAF"].map(
            lambda x: "black" if type(x) is float and np.isnan(x) else color_map[math.floor(x * 0.1)]
        )
        print(df_to_render["color"].value_counts())
        ejscreen_popup = folium.GeoJsonPopup(
            fields = ["PTRAF", "P_PTRAF"],
            aliases=["Traffic Proximity & Volume", "National Traffic Proximity & Volume Percentile"]
        )
        return folium.GeoJson(
            df_to_render,
            style_function=lambda x: {
                "fillColor": x["properties"]["color"],
                "weight": 0.5,
                "color": "grey"
            },
            popup=ejscreen_popup
        )
    