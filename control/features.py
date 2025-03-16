import geopandas as gpd
import pandas as pd
import osmnx as ox

def assimilate_routes() -> gpd.GeoDataFrame:
    """Loads airport-related features from OpenStreetMap using a custom filter."""
    airport_code = "KMDW"
    osm_filter = (
        '["aeroway"~"runway|taxiway|apron|control_tower|control_center|gate|hangar|'
        'helipad|heliport|navigationaid|taxilane|terminal|windsock|highway_strip|'
        'parking_position|holding_position|airstrip|stopway|tower"]'
    )
    graph = ox.graph_from_place(
        airport_code,
        simplify=False,
        retain_all=True,
        truncate_by_edge=True,
        custom_filter=osm_filter,
    )
    _, edges = ox.graph_to_gdfs(graph)
    return edges

def buffer_features(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Buffers geometries if width data is provided."""
    if 'width' in gdf.columns and not gdf['width'].isna().all():
        gdf_proj = gdf.to_crs(epsg=3857)
        gdf_proj['geometry'] = gdf_proj.apply(
            lambda row: row.geometry.buffer(float(row.width) / 2, cap_style=3)
            if pd.notna(row.width) else row.geometry,
            axis=1
        )
        return gdf_proj.to_crs(epsg=4326)
    return gdf

def generate_static_features(edges: gpd.GeoDataFrame):
    """
    Separates runway and taxiway features, applies buffering, and determines
    the center of the airport area.
    """
    if 'service' in edges.columns and any(s in edges['service'].unique() for s in ['runway', 'taxiway']):
        runways = edges[edges['service'] == 'runway'].copy()
        taxiways = edges[edges['service'] == 'taxiway'].copy()
    else:
        edges['ref'] = edges['ref'].fillna('')
        runways = edges[edges['ref'].str.contains('/')].copy()
        taxiways = edges[~edges['ref'].str.contains('/')].copy()

    runways = buffer_features(runways)
    taxiways = buffer_features(taxiways)

    if not runways.empty:
        center_lat = runways.geometry.centroid.y.mean()
        center_lon = runways.geometry.centroid.x.mean()
    elif not taxiways.empty:
        center_lat = taxiways.geometry.centroid.y.mean()
        center_lon = taxiways.geometry.centroid.x.mean()
    else:
        center_lat, center_lon = 41.7868, -87.7522  # Default: Chicago Midway
    return center_lat, center_lon, [runways, taxiways]