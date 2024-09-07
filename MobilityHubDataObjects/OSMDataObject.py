import pathlib
import geopandas as gpd
import osmnx as ox
import shapely
import folium

from .DataObject import DataObject

class OSMDataObject(DataObject):
    data_object = gpd.GeoDataFrame
    def __init__(self, cache_path: (str | pathlib.Path), tags): # TODO: not sure of type for tags so using any
        self.cache_path = cache_path
        self.tags = tags

    def load_data(
        self,
        load_area: (shapely.MultiPolygon | shapely.Polygon)
    ):
        old_cache_path = ox.settings.cache_folder
        ox.settings.cache_folder = self.cache_path
        gdf_osm_result = ox.features_from_polygon(load_area, self.tags)
        ox.settings.cache_folder = old_cache_path
        self.data_object = gdf_osm_result

    def get_folium_plot(self):
        osm_popup = folium.GeoJsonPopup(
            fields=["bicycle_parking", "capacity", "covered"],
            aliases=["Facility Type", "Capacity", "Covered?"],
            localize=True,
            labels=True,
        )
        osm_geojson = folium.GeoJson(
            self.data_object[["bicycle_parking", "capacity", "covered", "geometry"]],
            marker=folium.Marker(icon=folium.Icon(icon='square')),
            popup=osm_popup,
        )
        return osm_geojson

