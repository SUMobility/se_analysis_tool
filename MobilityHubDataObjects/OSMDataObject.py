import pathlib
import geopandas as gpd
import osmnx as ox
import shapely
import folium

from MobilityHubDataObjects.utils import basic_circle_marker, filter_two_corresponding_arrays, small_geodesic_polygons_to_points

from .DataObject import DataObject

class OSMDataObject(DataObject):
    data_object = gpd.GeoDataFrame
    def __init__(self, cache_path: (str | pathlib.Path), tags, max_point_size: int = 100): # TODO: not sure of type for tags so using any
        self.cache_path = cache_path
        self.tags = tags
        self.max_point_size = max_point_size

    def load_data(
        self,
        load_area: (shapely.MultiPolygon | shapely.Polygon)
    ):
        old_cache_path = ox.settings.cache_folder
        ox.settings.cache_folder = self.cache_path
        gdf_osm_result = ox.features_from_polygon(load_area, self.tags).to_crs(4326)
        ox.settings.cache_folder = old_cache_path
        gdf_osm_result.geometry = gdf_osm_result.geometry.map(
            lambda geom: small_geodesic_polygons_to_points(geom, self.max_point_size)
        )
        self.data_object = gdf_osm_result

    def get_folium_plot(self):
        intended_fields = ["bicycle_parking", "capacity", "covered"]
        intended_aliases = ["Facility Type", "Capacity", "Covered?"]
        fields, aliases = filter_two_corresponding_arrays(
            self.data_object.columns,
            intended_fields,
            intended_aliases,
        )
        print("FIELDS", intended_fields)
        print("ALIASES", intended_aliases)
        osm_popup = folium.GeoJsonPopup(
            fields=fields,
            aliases=aliases,
            localize=True,
            labels=True,
        )
        osm_geojson = folium.GeoJson(
            self.data_object[["bicycle_parking", "capacity", "covered", "geometry"]],
            marker=basic_circle_marker("red"),
            popup=osm_popup,
        )
        return osm_geojson

