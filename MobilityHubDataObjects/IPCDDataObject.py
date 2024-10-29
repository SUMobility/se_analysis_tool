import folium
from pandas.core.api import Series as Series
import shapely

from MobilityHubDataObjects.utils import basic_circle_marker, filter_two_corresponding_arrays, transform_shapely_geometry
from .SpatialDataObject import SpatialDataObject
import geopandas as gpd

class IPCDDataObject(SpatialDataObject):
    gdf = gpd.GeoDataFrame()
    def __init__(self, path) -> None:
        self.path = path
    
    def load_data(
        self,
        load_area: (shapely.MultiPolygon | shapely.Polygon),
        load_area_crs: int
    ) -> None:
        gdf_ipcd = gpd.read_file(self.path)
        ipcd_crs = gdf_ipcd.crs
        self.gdf = gdf_ipcd.loc[
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
            self.gdf.columns,
            intended_fields,
            intended_aliases
        )
        ipcd_popup = folium.GeoJsonPopup(
            fields=fields,
            aliases=aliases,
        )
        return folium.GeoJson(
            self.gdf,
            popup=ipcd_popup,
            marker=basic_circle_marker("red")
        )