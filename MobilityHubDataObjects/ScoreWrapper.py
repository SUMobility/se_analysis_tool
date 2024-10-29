import pandas as pd
import geopandas as gpd
import shapely
from MobilityHubDataObjects.constants import GEODESIC_CRS
from MobilityHubDataObjects.utils import get_scores_for_all_objects, transform_shapely_geometry


class ScoreWrapper:
    def __init__(self, objects, object_names, radius, local_crs: int) -> None:
        self.gdf_scores = get_scores_for_all_objects(objects, object_names).to_crs(local_crs)
        self.distance_functions = {name: object.get_score_decay_function() for name, object in zip(object_names, objects)}
        self.radius = radius
        self.local_crs = local_crs

    def get_score_at_point(self, point: shapely.Point, crs: int) -> float:
        point_transformed = transform_shapely_geometry(crs, self.local_crs, point)
        gdf_within_radius = self.gdf_scores.loc[self.gdf_scores.distance(point_transformed) < self.radius]
        # If this becomes too slow, a potentially faster way would be for decay functions to be a list of arguments to pass to pd.Series.agg
        all_decays = pd.Series(
            zip(gdf_within_radius.distance(point_transformed), gdf_within_radius["type"]), index=gdf_within_radius.index
        ).map(
            lambda x: self._apply_correct_score_decay_function(x[0], x[1]) 
        )
        all_decayed_scores = all_decays * gdf_within_radius["score"]
        return all_decayed_scores.sum()
    
    def get_score_at_point_geoseries(self, points: gpd.GeoSeries) -> pd.Series:
        return points.to_crs(self.local_crs).map(lambda x: self.get_score_at_point(x, self.local_crs))

    def _apply_correct_score_decay_function(self, distance: float, type: str):
        return self.distance_functions[type](distance)
        