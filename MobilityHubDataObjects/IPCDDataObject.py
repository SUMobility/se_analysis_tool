import folium
from shapely import MultiPolygon, Polygon

from MobilityHubDataObjects.utils import basic_circle_marker, filter_two_corresponding_arrays, transform_shapely_geometry
from .DataObject import DataObject
import geopandas as gpd

class IPCDDataObject(DataObject):
    data_object = gpd.GeoDataFrame()
    def __init__(self, path) -> None:
        self.path = path
    
    def load_data(
        self,
        load_area: MultiPolygon | Polygon | None,
        load_area_crs: int = 4326
    ) -> None:
        gdf_ipcd = gpd.read_file(self.path)
        ipcd_crs = gdf_ipcd.crs
        self.data_object = gdf_ipcd.loc[
            (
                (gdf_ipcd["geometry"].within(transform_shapely_geometry(load_area_crs, ipcd_crs, load_area)))
                 & (gdf_ipcd["MODE_BIKE"] == 1)
            ),
            ["BIKE_ID", "MODES_SERV", "geometry"]            
        ]
    
    def get_folium_plot(self) -> folium.GeoJson:
        # TODO: figure out error here
        intended_fields = ["BIKE_ID", "MODES_SERV"]
        intended_aliases = ["ID", "Modes Served"]
        fields, aliases = filter_two_corresponding_arrays(
            self.data_object.columns,
            intended_fields,
            intended_aliases
        )
        ipcd_popup = folium.GeoJsonPopup(
            fields=fields,
            aliases=aliases,
        )
        return folium.GeoJson(
            self.data_object,
            popup=ipcd_popup,
            marker=basic_circle_marker("red")
        )