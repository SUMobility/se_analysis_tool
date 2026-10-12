from __future__ import annotations

import pathlib
from typing import Any

import geopandas as gpd
import numpy as np
import osmnx as ox
import pandas as pd
from shapely.geometry.base import BaseGeometry


METERS_PER_MILE = 1609.344


DEFAULT_LANES_BY_HIGHWAY = {
    "motorway": 2.0,
    "motorway_link": 1.0,
    "trunk": 2.0,
    "trunk_link": 1.0,
    "primary": 2.0,
    "primary_link": 1.0,
    "secondary": 2.0,
    "secondary_link": 1.0,
    "tertiary": 2.0,
    "tertiary_link": 1.0,
    "residential": 2.0,
    "unclassified": 2.0,
    "service": 1.0,
}


def calculate_osm_intersection_metrics(
    base_gdf: gpd.GeoDataFrame,
    map_area: BaseGeometry,
    map_area_crs: int | str,
    projected_crs: int | str,
    cache_folder: str | pathlib.Path | None = None,
    request_timeout: int = 180,
) -> gpd.GeoDataFrame:
    """
    Calculate OSM-based intersection and roadway metrics for census
    block groups.

    The returned GeoDataFrame contains:

        Intersection Count
        Road Centerline Miles
        Road Lane Miles
        Intersections per Centerline Mile
        Intersections per Lane Mile
    """

    if base_gdf is None or base_gdf.empty:
        raise ValueError("base_gdf is empty.")

    if base_gdf.crs is None:
        raise ValueError("base_gdf must have a CRS.")

    if map_area is None or map_area.is_empty:
        raise ValueError("map_area is empty.")

    result_gdf = base_gdf.copy()

    old_cache_folder = None
    old_timeout = ox.settings.requests_timeout

    if cache_folder is not None:
        old_cache_folder = ox.settings.cache_folder
        ox.settings.cache_folder = pathlib.Path(cache_folder)

    try:
        ox.settings.use_cache = True
        ox.settings.requests_timeout = request_timeout

        # OSMnx requires geographic coordinates.
        map_area_geographic = (
            gpd.GeoSeries(
                [map_area],
                crs=map_area_crs,
            )
            .to_crs(epsg=4326)
            .iloc[0]
        )

        # Reproject block groups to a CRS with meter units.
        base_projected = result_gdf.to_crs(
            projected_crs
        ).copy()

        geoid_column = _find_geoid_column(base_projected)

        if geoid_column is None:
            raise KeyError(
                "Could not find a GEOID column or index in base_gdf. "
                f"Available columns: {base_projected.columns.tolist()}; "
                f"index name: {base_projected.index.name}"
            )

        base_projected[geoid_column] = (
            base_projected[geoid_column]
            .astype("string")
            .str.strip()
        )

        print(
            f"Using '{geoid_column}' as the block-group identifier."
        )

        # Download the OSM driving network.
        print("Downloading OSM street network...")

        graph = ox.graph_from_polygon(
            map_area_geographic,
            network_type="drive",
            simplify=True,
            retain_all=True,
            truncate_by_edge=True,
        )

        if graph.number_of_nodes() == 0:
            raise RuntimeError(
                "OSM returned an empty street network."
            )

        # Count streets using the original directed OSMnx graph.
        # count_streets_per_node internally handles conversion.
        street_counts = ox.stats.count_streets_per_node(graph)

        # Use an undirected graph for physical road-length calculations.
        graph_undirected = _to_undirected_graph(graph)

        graph_projected = ox.project_graph(
            graph_undirected,
            to_crs=projected_crs,
        )

        nodes_gdf, edges_gdf = ox.graph_to_gdfs(
            graph_projected,
            nodes=True,
            edges=True,
        )

        if edges_gdf.empty:
            raise RuntimeError(
                "OSM returned no street edges."
            )

        # Attach street counts to projected nodes.
        nodes_gdf["street_count"] = (
            nodes_gdf.index.to_series()
            .map(street_counts)
            .fillna(0)
        )

        # Nodes with at least three connected streets are intersections.
        intersections_gdf = nodes_gdf.loc[
            nodes_gdf["street_count"] >= 3
        ].copy()

        # Normalize highway classifications.
        if "highway" in edges_gdf.columns:
            edges_gdf["highway_class"] = (
                edges_gdf["highway"]
                .map(_get_highway_class)
            )
        else:
            edges_gdf["highway_class"] = pd.Series(
                None,
                index=edges_gdf.index,
                dtype="object",
            )

        # Parse lane counts from OSM.
        if "lanes" in edges_gdf.columns:
            edges_gdf["lanes_num"] = (
                edges_gdf["lanes"]
                .map(_parse_lanes)
            )
        else:
            edges_gdf["lanes_num"] = np.nan

        edges_gdf["lanes_num"] = pd.to_numeric(
            edges_gdf["lanes_num"],
            errors="coerce",
        )

        # Fill missing lanes using highway-class defaults.
        edges_gdf["lanes_num"] = (
            edges_gdf["lanes_num"]
            .fillna(
                edges_gdf["highway_class"]
                .map(DEFAULT_LANES_BY_HIGHWAY)
            )
            .fillna(1.0)
            .clip(lower=1.0)
        )

        # Keep only the columns needed for clipping.
        edges_for_overlay = edges_gdf[
            [
                "geometry",
                "lanes_num",
                "highway_class",
            ]
        ].copy()

        # Reset the index so GEOID exists only as a normal column.
        # This prevents GeoPandas index/column name conflicts.
        block_groups_for_overlay = base_projected[
            [
                geoid_column,
                "geometry",
            ]
        ].copy().reset_index(drop=True)

        print(
            "Clipping OSM roads to census block groups..."
        )

        edge_parts = gpd.overlay(
            edges_for_overlay,
            block_groups_for_overlay,
            how="intersection",
            keep_geom_type=True,
        )

        if edge_parts.empty:
            print(
                "No OSM road segments intersected the base polygons."
            )

            road_metrics = pd.DataFrame(
                columns=[
                    "Road Centerline Miles",
                    "Road Lane Miles",
                ]
            )
            road_metrics.index.name = geoid_column

        else:
            edge_parts = edge_parts.loc[
                edge_parts.geometry.notna()
                & ~edge_parts.geometry.is_empty
            ].copy()

            edge_parts["segment_miles"] = (
                edge_parts.geometry.length
                / METERS_PER_MILE
            )

            edge_parts["segment_lane_miles"] = (
                edge_parts["segment_miles"]
                * edge_parts["lanes_num"]
            )

            road_metrics = (
                edge_parts
                .groupby(geoid_column)
                .agg(
                    **{
                        "Road Centerline Miles": (
                            "segment_miles",
                            "sum",
                        ),
                        "Road Lane Miles": (
                            "segment_lane_miles",
                            "sum",
                        ),
                    }
                )
            )

        # Count intersection points by block group.
        if intersections_gdf.empty:
            intersections_by_block_group = pd.Series(
                dtype="float64",
                name="Intersection Count",
            )
            intersections_by_block_group.index.name = (
                geoid_column
            )

        else:
            # Reset both indexes before spatial join. GEOID remains only
            # as a regular column in the block-group GeoDataFrame.
            intersection_points_for_join = (
                intersections_gdf[
                    [
                        "geometry",
                        "street_count",
                    ]
                ]
                .reset_index(drop=True)
            )

            block_groups_for_join = (
                block_groups_for_overlay[
                    [
                        geoid_column,
                        "geometry",
                    ]
                ]
                .reset_index(drop=True)
            )

            intersection_assignments = gpd.sjoin(
                intersection_points_for_join,
                block_groups_for_join,
                how="left",
                predicate="within",
                lsuffix="intersection",
                rsuffix="block_group",
            )

            intersections_by_block_group = (
                intersection_assignments
                .dropna(subset=[geoid_column])
                .groupby(geoid_column)
                .size()
                .rename("Intersection Count")
            )

        # Combine roadway and intersection metrics.
        metrics = pd.concat(
            [
                road_metrics,
                intersections_by_block_group,
            ],
            axis=1,
        )

        metrics.index = (
            metrics.index
            .astype("string")
            .str.strip()
        )
        metrics.index.name = geoid_column

        # Normalize GEOIDs in the output GeoDataFrame.
        if geoid_column not in result_gdf.columns:
            result_gdf[geoid_column] = (
                result_gdf.index
                .astype("string")
                .str.strip()
            )
        else:
            result_gdf[geoid_column] = (
                result_gdf[geoid_column]
                .astype("string")
                .str.strip()
            )
            
        result_gdf = result_gdf.reset_index(
            drop=True
        )

        metrics_for_merge = metrics.reset_index()

        metrics_for_merge[geoid_column] = (
            metrics_for_merge[geoid_column]
            .astype("string")
            .str.strip()
        )

        # Join the calculated metrics to the block groups.
        result_gdf = result_gdf.merge(
            metrics_for_merge,
            on=geoid_column,
            how="left",
        )

        # Fill missing values for block groups without roads or
        # intersections.
        for column in [
            "Intersection Count",
            "Road Centerline Miles",
            "Road Lane Miles",
        ]:
            if column not in result_gdf.columns:
                result_gdf[column] = 0.0

            result_gdf[column] = (
                pd.to_numeric(
                    result_gdf[column],
                    errors="coerce",
                )
                .fillna(0.0)
            )

        # Calculate intersections per centerline mile.
        result_gdf[
            "Intersections per Centerline Mile"
        ] = np.where(
            result_gdf["Road Centerline Miles"] > 0,
            (
                result_gdf["Intersection Count"]
                / result_gdf["Road Centerline Miles"]
            ),
            np.nan,
        )

        # Calculate intersections per lane mile.
        result_gdf[
            "Intersections per Lane Mile"
        ] = np.where(
            result_gdf["Road Lane Miles"] > 0,
            (
                result_gdf["Intersection Count"]
                / result_gdf["Road Lane Miles"]
            ),
            np.nan,
        )

        # Return to the original CRS.
        result_gdf = result_gdf.to_crs(base_gdf.crs)

        # Preserve the original base-layer convention where GEOID is
        # the index.
        result_gdf = result_gdf.set_index(
            geoid_column,
            drop=True,
        )
        result_gdf.index.name = "GEOID"

        print(
            "OSM intersection metrics calculated successfully."
        )

        print(
            result_gdf[
                [
                    "Intersection Count",
                    "Road Centerline Miles",
                    "Road Lane Miles",
                    "Intersections per Lane Mile",
                ]
            ].head()
        )

        return result_gdf

    finally:
        if old_cache_folder is not None:
            ox.settings.cache_folder = old_cache_folder

        ox.settings.requests_timeout = old_timeout


def _find_geoid_column(
    gdf: gpd.GeoDataFrame,
) -> str | None:
    """
    Find the block-group GEOID column or promote the GEOID index.
    """

    # Check for a regular GEOID column.
    for column in [
        "GEOID",
        "geoid",
        "GEOID10",
        "GEOID20",
    ]:
        if column in gdf.columns:
            return column

    # Handle a named GEOID index.
    if gdf.index.name is not None:
        index_name = str(
            gdf.index.name
        ).strip().lower()

        if index_name in {
            "geoid",
            "geoid10",
            "geoid20",
        }:
            gdf["GEOID"] = (
                gdf.index
                .astype("string")
                .str.strip()
            )
            return "GEOID"

    # Handle an unnamed index containing 11-digit GEOIDs.
    if len(gdf.index) > 0:
        index_values = pd.Series(
            gdf.index.to_numpy(),
            dtype="string",
        ).str.strip()

        valid_values = (
            index_values.notna()
            & index_values.str.fullmatch(r"\d{11}")
        )

        if valid_values.all():
            gdf["GEOID"] = index_values.to_numpy()
            return "GEOID"

    return None


def _parse_lanes(
    value: Any,
) -> float:
    """
    Parse OSM lanes values such as:

        2
        "2"
        "2;3"
        ["2", "3"]

    For values such as "2;3", the first numeric value is used.
    """

    if value is None:
        return np.nan

    if isinstance(value, list):
        values = value
    else:
        try:
            if pd.isna(value):
                return np.nan
        except (TypeError, ValueError):
            pass

        values = (
            str(value)
            .replace(";", "|")
            .split("|")
        )

    for item in values:
        try:
            return float(
                str(item).strip()
            )
        except (
            TypeError,
            ValueError,
        ):
            continue

    return np.nan


def _get_highway_class(
    value: Any,
) -> str | None:
    """
    Normalize OSM highway values.

    OSM may provide highway values as strings or lists.
    """

    if value is None:
        return None

    if isinstance(value, list):
        if not value:
            return None

        return str(value[0]).strip()

    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    return str(value).split(";")[0].strip()


def _to_undirected_graph(
    graph: Any,
) -> Any:
    """
    Convert an OSMnx graph to an undirected graph across OSMnx versions.
    """

    try:
        return ox.convert.to_undirected(graph)
    except AttributeError:
        pass

    try:
        return ox.utils_graph.get_undirected(graph)
    except AttributeError as error:
        raise RuntimeError(
            "This OSMnx version does not provide a supported "
            "directed-to-undirected graph conversion method."
        ) from error