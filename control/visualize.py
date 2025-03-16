import folium
from folium.plugins import MousePosition

from typing import List, Dict
import geopandas as gpd
import pandas as pd

# Global plane color mapping and palette
PLANE_COLORS = {}
COLOR_PALETTE = [
    "purple", "green", "blue", "orange", "brown",
    "pink", "gray", "black", "red", "cadetblue",
    "darkgreen", "darkpurple"
]

def get_plane_color(tail: str) -> str:
    """Assigns a unique color to each plane based on its tail number."""
    if tail not in PLANE_COLORS:
        index = len(PLANE_COLORS) % len(COLOR_PALETTE)
        PLANE_COLORS[tail] = COLOR_PALETTE[index]
    return PLANE_COLORS[tail]

def build_interactive_map(center_lat: float, center_lon: float,
                          static_features: List[gpd.GeoDataFrame],
                          flight_geojson: Dict,
                          plane_histories: Dict[str, pd.DataFrame],
                          flagged_events: List[Dict]) -> folium.Map:
    """Constructs and layers an interactive Folium map with static and dynamic flight features."""
    m = folium.Map(location=[center_lat, center_lon], zoom_start=10, tiles="cartodbpositron")
    MousePosition(
        position="topright",
        separator=" | ",
        prefix="Lat/Long:",
        lat_formatter="function(num) {return L.Util.formatNum(num, 5);}",
        lng_formatter="function(num) {return L.Util.formatNum(num, 5);}"
    ).add_to(m)

    runways, taxiways = static_features
    if not runways.empty:
        folium.GeoJson(
            runways.__geo_interface__,
            name="Runways",
            style_function=lambda f: {'color': 'orange', 'weight': 2, 'fillOpacity': 0.2},
            tooltip=folium.GeoJsonTooltip(fields=["ref", "name"], aliases=["Ref", "Name"], localize=True)
        ).add_to(m)
    if not taxiways.empty:
        folium.GeoJson(
            taxiways.__geo_interface__,
            name="Taxiways",
            style_function=lambda f: {'color': 'lightgray', 'weight': 2, 'fillOpacity': 0.2},
            tooltip=folium.GeoJsonTooltip(fields=["ref", "name"], aliases=["Ref", "Name"], localize=True)
        ).add_to(m)

    for feature in flight_geojson["features"]:
        geom = feature["geometry"]
        props = feature["properties"]
        if geom["type"] == "Point":
            lon_pt, lat_pt = geom["coordinates"]
            marker_type = props.get("markerType", "")
            icon_color = "green" if marker_type == "current" else "red" if marker_type == "predicted" else "blue"
            popup_text = f"Tail: {props.get('tail_number')} | Speed: {props.get('speed')} m/s"
            if props.get("compliance"):
                popup_text += f"<br>{props.get('compliance')}"
            folium.Marker(
                location=[lat_pt, lon_pt],
                icon=folium.Icon(color="white", icon_color=icon_color, icon="plane"),
                popup=popup_text
            ).add_to(m)
        elif geom["type"] == "LineString":
            dash = "6, 6" if props.get("lineType") == "projected" else None
            coords = [[c[1], c[0]] for c in geom["coordinates"]]
            folium.PolyLine(
                locations=coords,
                color=props.get("planeColor", "purple"),
                weight=4,
                dash_array=dash
            ).add_to(m)

    for tail, df in plane_histories.items():
        for _, row in df.iterrows():
            folium.CircleMarker(
                location=[row["lat"], row["lon"]],
                radius=2,
                color=get_plane_color(tail),
                fill=True,
                fill_opacity=0.7,
                tooltip=f"Timestamp: {row['Timestamp']}"
            ).add_to(m)

    for event in flagged_events:
        folium.Circle(
            location=[event["lat"], event["lon"]],
            radius=50,
            color="yellow",
            fill=True,
            fill_color="yellow",
            fill_opacity=0.35,
            popup=(f"Flagged incursion for plane {event['tail']} (ref: {event['ref']})<br>"
                   f"Occurred at timestamp {event['timestamp']}<br>{event['message']}"),
            tooltip=f"Timestamp: {event['timestamp']}"
        ).add_to(m)

    folium.LayerControl().add_to(m)
    return m