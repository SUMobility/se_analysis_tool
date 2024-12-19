import pathlib
from typing import Callable, Iterable
import folium
import geopandas as gpd
import numpy as np
import pandas as pd
import pygris
from pygris.utils import erase_water
import shapely
from scipy.spatial import KDTree
import time

from MobilityHubDataObjects import SpatialDataObject
from MobilityHubDataObjects.constants import GEODESIC_CRS
from .ColorMaps import ColorMaps
from .constants import ACS_YEAR, BUFFER_SIZE, EJSCREEN_NAME, GEOID_COLUMN, GEOID_NAME, TIGER_CRS
from .entities import BaseLayerMetric
from MobilityHubDataObjects.utils import transform_shapely_geometry

class BaseLayer(SpatialDataObject):
    def __init__(self, metrics: Iterable[BaseLayerMetric], counties_path: str | pathlib.Path, local_crs: int, color_map: ColorMaps, smooth: bool):
        self.metrics = metrics
        self.counties_path = pathlib.Path(counties_path).resolve()
        self.local_crs = local_crs
        # Get the color map function
        self.color_map_function = color_map.value
        self.smooth = smooth
    def load_data(
        self,
        load_area: (shapely.MultiPolygon | shapely.Polygon),
        load_area_crs: int
    ):
        # Load a gdf of counties
        gdf_counties = gpd.read_file(
            self.counties_path,
            mask=(transform_shapely_geometry(load_area_crs, TIGER_CRS, load_area))
        )
        # Shrink the load area slightly to avoid getting bordering geometries
        load_area_shrunk = transform_shapely_geometry(
            self.local_crs, load_area_crs, shapely.buffer(
                transform_shapely_geometry(
                    load_area_crs, self.local_crs, load_area
                ), BUFFER_SIZE
            )
        )
        gdf_counties = gdf_counties.loc[gdf_counties.intersects(load_area_shrunk)]
        # Get the TIGER block group data
        gdf_tiger = pd.concat(
            gdf_counties[GEOID_COLUMN].map(
                lambda counties_fips: pygris.block_groups(
                    state=counties_fips[:2],
                    county=counties_fips[2:5],
                    year=ACS_YEAR,
                    cache=True
                )
            ).values
        )
        gdf_tiger = erase_water(gdf_tiger.loc[gdf_tiger.intersects(load_area)])
        gdf_tiger = gdf_tiger.set_index("GEOID")
        block_group_kd_tree = None
        block_group_centroids = gdf_tiger.to_crs(self.local_crs).centroid
        if self.smooth:
            print("generating kd tree")
            block_group_kd_tree = KDTree(
                np.array([[point.x, point.y] for point in block_group_centroids])
            )
            print("generated kd tree")
        metric_names = []
        for metric in self.metrics:
            # Load each metric
            if metric.should_send_block_group_gdf():
                metric.send_block_group_gdf(gdf_tiger)
            if not metric.get_is_loaded():
                metric.load_data(gdf_counties[GEOID_COLUMN].values)
            metric_series = metric.get_data_for_ids(gdf_tiger.index)
            print(f"Loaded {metric_series.name}")
            if self.smooth:
                assert block_group_kd_tree is not None
                gdf_tiger[metric_series.name] = kde_smoothing(metric_series, block_group_centroids, block_group_kd_tree)
            else:
                gdf_tiger[metric_series.name] = metric_series
            metric_names.append(metric_series.name)
        self.metric_names = list(metric_names)
        self.gdf = gdf_tiger
        self._set_is_loaded()

    def get_folium_plot(self):
        gdf_to_render = gpd.GeoDataFrame(
            self.gdf[self.metric_names],
            geometry=self.gdf.geometry
        )
        gdf_to_render["color"] = self.color_map_function(
            gdf_to_render[self.metric_names]
        )
        popup = folium.GeoJsonPopup(
            fields=self.metric_names + [GEOID_NAME]
        )
        return folium.GeoJson(
            gdf_to_render.reset_index(names=GEOID_NAME),
            style_function=lambda x: {
                "fillColor": x["properties"]["color"],
                "weight": 0.5,
                "color": "grey"
            },
            popup=popup
        ) 

    def get_score_decay_function(self) -> Callable[[float], float]:
        raise NotImplementedError()
    
    def get_scores(self) -> pd.Series:
        raise NotImplementedError

def kde_smoothing(data: pd.Series, points: gpd.GeoSeries, kd_tree: KDTree, k=5, bandwidth=0.005, distances_factor = 1/100000):
    """
    Run a kde smoothing algorithm

    :param data: a Pandas Series containing data associated with each element of geom
    :param points: a Geopandas GeoSeries of points associated with data. Must be identically shaped with data
    :param kd_tree: a Kernel Density tree containing each entry of geom. #TODO: allow this to be generated if None is specified
    :param k: the number of geometries to query for. higher = more smoothing, defaults to 5
    :param bandwidth: the bandwidth parameter for the Gaussian smopthing algorithm. Higher bandwith = further points have more weight, defaults to 0.1
    :param distances_factor: the amount to multiply distances by, defaults to 1/100000 to keep values of d^2 reasonably sized and avoid floating point error
    """
    assert data.index.size == points.index.size and (data.index == points.index).all()
    # Handle each column, running columns without na values in bulk and running columns with na values together
    #count_na_values = {column: data[column].isna().sum() for column in data.columns}
    data_dropped = data.dropna()
    points = points.reindex_like(data_dropped)
    any_values_dropped = data_dropped.size != data.size
    value_is_dropped = ~data.index.isin(data_dropped.index)
    smoothed_values = np.zeros_like(data)
    data_array = data.to_numpy()
    geom_array = np.array([[point.x, point.y] for point in points])
    for i, point in enumerate(geom_array):
        if value_is_dropped[i]:
            continue
        distances, indices = kd_tree.query(point, k=k)
        if any_values_dropped:
            i = 0
            while True:
                selected_value_is_dropped = [value_is_dropped[i] for i in indices]
                if not np.any(selected_value_is_dropped):
                    break
                count_dropped = np.sum(selected_value_is_dropped)
                old_indices = indices
                old_distances = distances
                new_distances, new_indices = kd_tree.query(point, k=k+count_dropped)
                indices = np.array([
                    i for i in new_indices if not (value_is_dropped[i] and i in old_indices)
                ])
                distances = np.array([
                    dist for i, dist in enumerate(new_distances) if not (
                        value_is_dropped[new_indices[i]] and new_indices[i] in old_indices
                    )
                ])
                if len(indices) != len(distances):
                    print(indices, distances)
                    assert True==False #WHY WOULD THIS EVER HAPPEN
                if i > 20:
                    print("WARN: trapped in an infinite loop, using k < specified k")
                    indices = np.array([
                        i for i in old_indices if not value_is_dropped[i]
                    ])
                    distances = np.array([
                        dist for i, dist in enumerate(old_distances) if not value_is_dropped[old_indices[i]]
                    ])
                    break
                i += 1
        weights = np.exp(-(distances * distances_factor) ** 2 / (2 * bandwidth ** 2))
        smoothed_values[i] = np.sum(data_array[indices] * weights) / np.sum(weights)
    return pd.Series(
        smoothed_values,
        index=data.index
    ).loc[~value_is_dropped].copy().reindex_like(data)
