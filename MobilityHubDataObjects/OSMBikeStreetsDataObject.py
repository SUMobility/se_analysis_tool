import pathlib
from typing import Callable
import folium
from folium.features import GeoJson
import numpy as np
import osmnx as ox
import pandas as pd
import geopandas as gpd
from shapely import MultiPolygon, Polygon
import shapely
from MobilityHubDataObjects import SpatialDataObject
from MobilityHubDataObjects.constants import GEODESIC_CRS
from MobilityHubDataObjects.utils import transform_shapely_geometry

# TODO: move constants
paint_bike_lane_types = ["lane", "share_busway"]
protected_bike_lane_types = ["track"]
bike_exclude = ["no", "discouraged"]
bike_include = ["yes", "designated", "permissive"]
path_bike_not_allowed_usually = ["footway", "bridleway", "ramp"]
path_bike_allowed_usually = ["cycleway", "path"]
cycleway_tag_types = ["cycleway", "cycleway:left", "cycleway:right", "cycleway:both"]
#TODO: handle bicycle_road, cyclestreet, bike routes
#TODO check one way for cycleway, paths, other modifiers that I don't think we're catching
bike_lane_tags = {
    "cycleway": paint_bike_lane_types + protected_bike_lane_types,
    "highway": path_bike_allowed_usually + path_bike_not_allowed_usually,
    "cycleway:left": paint_bike_lane_types + protected_bike_lane_types,
    "cycleway:right": paint_bike_lane_types + protected_bike_lane_types,
    "cycleway:both": paint_bike_lane_types + protected_bike_lane_types,
    "ramp: bicycle": True,
}
BIKE_LANE_COLORS = {
    "paint_only": "#1cff03",
    "not_paint_only": "#21c90e"
}
DEFAULT_REFERENCE_DISTANCE = 4829 # 3 miles

class OSMBikeStreetsDataObject(SpatialDataObject):
    def __init__(
            self,
            cache_path: (str | pathlib.Path),
            max_distance_from_reference: int | None = DEFAULT_REFERENCE_DISTANCE,
            reference: SpatialDataObject | None = None,
            local_crs: int | None = int
        ):
        self.cache_path = cache_path
        self.max_distance_from_reference = max_distance_from_reference
        self.reference = reference
        self.local_crs = local_crs
        if reference is not None and (max_distance_from_reference is None or local_crs is None):
            raise RuntimeError("Reference provided but CRS and/or max_distance_from_reference not provided. All three parameters must be provided together if reference is provided")
    
    def load_data(self, load_area: MultiPolygon | Polygon, load_area_crs: int) -> None:
        if self.reference is not None:
            assert self.reference.get_is_loaded()
        old_cache_path = ox.settings.cache_folder
        ox.settings.cache_folder = self.cache_path
        if self.reference is not None:
            reference_geom = self.reference.gdf.geometry.to_crs(self.local_crs).buffer(self.max_distance_from_reference).unary_union
            load_area_geom = transform_shapely_geometry(
                self.local_crs,
                GEODESIC_CRS,
                shapely.intersection(
                    transform_shapely_geometry(load_area_crs, self.local_crs, load_area),
                    reference_geom
                )
            )
        else:
            load_area_geom = transform_shapely_geometry(load_area_crs, GEODESIC_CRS, load_area)
        gdf_osm_result = ox.features_from_polygon(
            load_area_geom,
            bike_lane_tags
        )
        gdf_osm_result["geometry"] = gdf_osm_result.geometry
        osm_crs = gdf_osm_result.crs
        for tag in bike_lane_tags.keys():
            if tag not in gdf_osm_result:
                gdf_osm_result[tag] = np.nan
        df_osm_processed_separated = pd.concat([
            gdf_osm_result.loc[ # Paths that usually include bikes and are not excluded
                gdf_osm_result["highway"].isin(path_bike_allowed_usually) 
                & ~gdf_osm_result["bicycle"].isin(bike_exclude)
            ],
            gdf_osm_result.loc[ # Paths that do not usually include bikes, but where bikes are included
                gdf_osm_result["highway"].isin(path_bike_not_allowed_usually)
                & gdf_osm_result["bicycle"].isin(bike_include)
            ],
            *[gdf_osm_result.loc[ # Protected bike lanes (includes flexposts)
                gdf_osm_result[cycleway_type].isin(protected_bike_lane_types)
            ] for cycleway_type in cycleway_tag_types],
            gdf_osm_result.loc[gdf_osm_result["ramp: bicycle"] == "yes"]
        ])
        df_osm_processed_separated = df_osm_processed_separated[
            ~df_osm_processed_separated.index.duplicated(keep="first")
        ]
        df_osm_processed_separated["paint_only"] = False
        df_osm_processed_not_separated = pd.concat([
            gdf_osm_result.loc[ # Paint-only bike lanes
                gdf_osm_result[cycleway_type].isin(paint_bike_lane_types)
            ] for cycleway_type in cycleway_tag_types
        ])
        df_osm_processed_not_separated["paint_only"] = True
        gdf_osm_processed = pd.concat(
            [df_osm_processed_not_separated, df_osm_processed_separated]
        ).sort_values(["cycleway", "paint_only"], ascending=False, kind="stable")
        gdf_osm_processed = gdf_osm_processed.loc[
            ~gdf_osm_processed.index.duplicated(keep="first")
        ]
        self.gdf = gpd.GeoDataFrame(gdf_osm_processed.reset_index(), geometry="geometry", crs=osm_crs)
        ox.settings.cache_folder = old_cache_path
        self._set_is_loaded()
    
    def get_folium_plot(self) -> GeoJson:
        fields = ["cycleway", "highway", "paint_only"]
        aliases = ["Cycleway Type", "Road Type", "Paint Only?"]
        bike_lane_popup = folium.GeoJsonPopup(
            fields=fields,
            aliases=aliases
        )
        return folium.GeoJson(
            data=self.gdf,
            popup=bike_lane_popup,
            style_function=lambda x: {
                "color": BIKE_LANE_COLORS["paint_only"] if x["properties"]["paint_only"] else BIKE_LANE_COLORS["not_paint_only"],
                "weight": 4,
            }
        ) 
    
    def get_score_decay_function(self) -> Callable[[float], float]:
        raise NotImplementedError()
    
    def get_scores(self) -> pd.Series:
        raise NotImplementedError()