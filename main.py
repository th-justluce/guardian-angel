import math
import json
import folium
import osmnx as ox
import geopandas as gpd
import pandas as pd
from typing import List, Dict, Tuple
from geopy.distance import distance
from shapely.geometry import LineString
from folium.plugins import MousePosition

from adsb.adsb_manager import AircraftTracker

# Global dictionary for unique plane colors
plane_colors = {}
color_palette = [
    "purple", "green", "blue", "orange", "brown",
    "pink", "gray", "black", "red", "cadetblue",
    "darkgreen", "darkpurple"
]

def get_plane_color(tail: str) -> str:
    """Returns a unique color for each plane, cycling through a palette."""
    if tail not in plane_colors:
        index = len(plane_colors) % len(color_palette)
        plane_colors[tail] = color_palette[index]
    return plane_colors[tail]

# Global dictionary to store first flagged incursion events.
# Keys are (tail, instruction_ref) and values are event info.
flagged_incursions = {}

# -------------------------------------------------------------------
# Global logic for static features
# -------------------------------------------------------------------
def assimilate_routes() -> gpd.GeoDataFrame:
    """
    Loads static airport data using OSMnx with a custom filter.
    """
    airport_icao_code = "KMDW"
    osm_filter = (
        '["aeroway"~"runway|taxiway|apron|control_tower|control_center|gate|hangar|'
        'helipad|heliport|navigationaid|taxilane|terminal|windsock|highway_strip|'
        'parking_position|holding_position|airstrip|stopway|tower"]'
    )
    G = ox.graph_from_place(
        airport_icao_code,
        simplify=False,
        retain_all=True,
        truncate_by_edge=True,
        custom_filter=osm_filter,
    )
    _, gdf_edges = ox.graph_to_gdfs(G)
    return gdf_edges

def buffer_features(gdf: gpd.GeoDataFrame):
    """
    Buffers runway/taxiway geometries if width data is available.
    """
    if 'width' in gdf.columns and not gdf['width'].isna().all():
        gdf_m = gdf.to_crs(epsg=3857)
        gdf_m['geometry'] = gdf_m.apply(
            lambda x: x.geometry.buffer(float(x.width) / 2, cap_style=3)
            if not pd.isna(x.width) else x.geometry,
            axis=1
        )
        return gdf_m.to_crs(epsg=4326)
    return gdf

def generate_static_features(edges: gpd.GeoDataFrame):
    """
    Splits edges into runways/taxiways, buffers them,
    and returns the center coordinates and processed feature groups.
    Also, tooltips are added to display the "ref" and "name".
    """
    if 'service' in edges.columns and (
        'runway' in edges['service'].unique() or 'taxiway' in edges['service'].unique()
    ):
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
        center_lat, center_lon = 41.7868, -87.7522  # Approx Chicago Midway
    return center_lat, center_lon, [runways, taxiways]

# -------------------------------------------------------------------
# Flight path and compliance logic
# -------------------------------------------------------------------
def predict_position(lat, lon, bearing, speed, t):
    """
    Given a starting lat, lon, bearing (degrees), and speed (m/s),
    compute the destination after t seconds.
    """
    d = speed * t
    origin = (lat, lon)
    destination = distance(meters=d).destination(origin, bearing)
    return destination.latitude, destination.longitude

def evaluate_compliance(
    instructions: List[Dict],
    plane: str,
    current_lat: float,
    current_lon: float,
    predicted_lat: float,
    predicted_lon: float,
    speed: float,
    static_features: List[gpd.GeoDataFrame],
    simulation_time: float
) -> Dict[str, str]:
    """
    Evaluates flight path compliance.
    Filters instructions by mapping the flight name to the ADS-B identifier and ensuring the instruction's time is reached.
    """
    # Filter instructions using the mapped flight identifier and the adjusted simulation time
    relevant_instr = [
        instr for instr in instructions
        if map_flight_identifier(instr["plane"]) == plane and instr["time"] <= simulation_time
    ]
    if not relevant_instr:
        return {"message": "No active instruction for compliance evaluation.", "ref": ""}
    
    current_instr = max(relevant_instr, key=lambda x: x["time"])
    instr_ref = current_instr["reference"]
    command = current_instr["instr"]

    line = LineString([(current_lon, current_lat), (predicted_lon, predicted_lat)])
    found_feature = None
    for feature_group in static_features:
        for idx, row in feature_group.iterrows():
            ref_val = str(row.get("ref", "")).strip()
            if ref_val == instr_ref:
                found_feature = row.geometry
                break
        if found_feature is not None:
            break

    if found_feature is None:
        return {"message": f"No matching feature found for reference {instr_ref}.", "ref": instr_ref}

    intersects = line.intersects(found_feature)
    landing_max_speed = 25.0
    crossing_min_speed = 5.0
    hold_speed_threshold = 1.0

    if command == "CLEARED_TO_LAND":
        if intersects:
            if speed <= landing_max_speed:
                return {"message": f"In compliance: CLEARED TO LAND on {instr_ref} at safe speed.", "ref": instr_ref}
            else:
                return {"message": f"Non-compliant: Approaching runway {instr_ref} too fast.", "ref": instr_ref}
        else:
            return {"message": f"Non-compliant: Predicted path does not intersect runway {instr_ref}.", "ref": instr_ref}
    elif command == "CLEAR_TO_CROSS":
        if intersects:
            if speed >= crossing_min_speed:
                return {"message": f"In compliance: CLEARED TO CROSS {instr_ref} while moving.", "ref": instr_ref}
            else:
                return {"message": f"Non-compliant: Aircraft is not moving while cleared to cross {instr_ref}.", "ref": instr_ref}
        else:
            return {"message": f"Non-compliant: Predicted path does not intersect taxiway {instr_ref}.", "ref": instr_ref}
    elif command == "HOLD_SHORT":
        if intersects:
            if speed <= hold_speed_threshold:
                return {"message": f"In compliance: HOLD_SHORT at {instr_ref} (aircraft stationary).", "ref": instr_ref}
            else:
                return {"message": f"Non-compliant: Aircraft is moving into {instr_ref} despite HOLD_SHORT.", "ref": instr_ref}
        else:
            return {"message": f"In compliance: No incursion of {instr_ref} as required by HOLD_SHORT.", "ref": instr_ref}
    else:
        return {"message": f"Unknown command: {command}", "ref": instr_ref}

def log_flagged_incursions(
    plane_histories: Dict[str, pd.DataFrame],
    instructions: List[Dict],
    static_features: List[gpd.GeoDataFrame],
    interval: int = 60
) -> List[Dict]:
    """
    Iterates over each record in each plane’s history.
    If a non-compliant incursion is detected and hasn't been logged yet for that plane/instruction,
    logs it and returns a list of flagged incursion events.
    """
    events = []
    for tail, df in plane_histories.items():
        df = df.sort_values("Timestamp")
        for _, row in df.iterrows():
            lat = row["lat"]
            lon = row["lon"]
            bearing = row["Direction"]
            speed = row["Speed"]
            tstamp = row["Timestamp"]
            predicted_latitude, predicted_longitude = predict_position(lat, lon, bearing, speed, interval)
            result = evaluate_compliance(
                instructions=instructions,
                plane=tail,
                current_lat=lat,
                current_lon=lon,
                predicted_lat=predicted_latitude,
                predicted_lon=predicted_longitude,
                speed=speed,
                static_features=static_features,
                simulation_time=float(tstamp) + interval  # Adjusted simulation time
            )

            if "Non-compliant" in result["message"]:
                key = (tail, result["ref"])
                if key not in flagged_incursions:
                    flagged_incursions[key] = {
                        "tail": tail,
                        "timestamp": tstamp,
                        "lat": lat,
                        "lon": lon,
                        "message": result["message"],
                        "ref": result["ref"]
                    }
                    print(f"[FLAGGED INCURSION] Plane {tail} at timestamp {tstamp}: {result['message']}")
                    events.append(flagged_incursions[key])
    return events

def build_flight_path_geojson(
    plane_histories: Dict[str, pd.DataFrame],
    instructions: List[Dict],
    static_features: List[gpd.GeoDataFrame],
    interval: int = 60
) -> Dict:
    """
    Builds a GeoJSON FeatureCollection for each plane:
      - A single line for the entire historical path (with plane-specific color)
      - A 'current' position marker (green)
      - A 'predicted' position marker (red) with compliance info
      - A projected line from current to predicted (dashed, in plane color)
    """
    features = []
    for tail, df in plane_histories.items():
        df = df.sort_values("Timestamp")
        if df.empty:
            continue
        plane_color = get_plane_color(tail)
        history_coords = [[row["lon"], row["lat"]] for _, row in df.iterrows()]
        if len(history_coords) > 1:
            features.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": history_coords},
                "properties": {
                    "lineType": "history",
                    "tail_number": tail,
                    "planeColor": plane_color
                }
            })
        last_row = df.iloc[-1]
        lat = last_row["lat"]
        lon = last_row["lon"]
        bearing = last_row["Direction"]
        speed = last_row["Speed"]
        tstamp = last_row["Timestamp"]
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "markerType": "current",
                "tail_number": tail,
                "timestamp": tstamp,
                "speed": speed
            }
        })
        pred_lat, pred_lon = predict_position(lat, lon, bearing, speed, interval)
        compliance_result = evaluate_compliance(
            instructions=instructions,
            plane=tail,
            current_lat=lat,
            current_lon=lon,
            predicted_lat=pred_lat,
            predicted_lon=pred_lon,
            speed=speed,
            static_features=static_features,
            simulation_time=float(tstamp)
        )
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [pred_lon, pred_lat]},
            "properties": {
                "markerType": "predicted",
                "tail_number": tail,
                "timestamp": tstamp,
                "speed": speed,
                "compliance": compliance_result["message"]
            }
        })
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[lon, lat], [pred_lon, pred_lat]]},
            "properties": {
                "lineType": "projected",
                "tail_number": tail,
                "planeColor": plane_color
            }
        })
    return {"type": "FeatureCollection", "features": features}

# -------------------------------------------------------------------
# Folium-based visualization
# -------------------------------------------------------------------
def build_interactive_map(
    center_lat: float,
    center_lon: float,
    static_features: List[gpd.GeoDataFrame],
    flight_geojson: Dict,
    plane_histories: Dict[str, pd.DataFrame],
    flagged_events: List[Dict]
) -> folium.Map:
    """
    Constructs an interactive Folium map with:
      - Runway/taxiway layers (with tooltips for edge names and refs),
      - Flight path features,
      - Historical point markers (with timestamp tooltips),
      - Circle markers for flagged incursion regions,
      - A live mouse position indicator.
    """
    m = folium.Map(location=[center_lat, center_lon], zoom_start=10, tiles="cartodbpositron")
    MousePosition(
        position="topright",
        separator=" | ",
        prefix="Lat/Long:",
        lat_formatter="function(num) {return L.Util.formatNum(num, 5);}",
        lng_formatter="function(num) {return L.Util.formatNum(num, 5);}"
    ).add_to(m)
    
    # Add static features with tooltips showing 'ref' and 'name'
    runways, taxiways = static_features
    if not runways.empty:
        folium.GeoJson(
            runways.__geo_interface__,
            name="Runways",
            style_function=lambda f: {'color': 'red', 'weight': 2, 'fillOpacity': 0.3},
            tooltip=folium.GeoJsonTooltip(fields=["ref", "name"], aliases=["Ref", "Name"], localize=True)
        ).add_to(m)
    if not taxiways.empty:
        folium.GeoJson(
            taxiways.__geo_interface__,
            name="Taxiways",
            style_function=lambda f: {'color': 'white', 'weight': 2, 'fillOpacity': 0.3},
            tooltip=folium.GeoJsonTooltip(fields=["ref", "name"], aliases=["Ref", "Name"], localize=True)
        ).add_to(m)
    
    # Add flight path features (markers and lines)
    for feature in flight_geojson["features"]:
        geom_type = feature["geometry"]["type"]
        coords = feature["geometry"]["coordinates"]
        props = feature["properties"]
        if geom_type == "Point":
            lon_pt, lat_pt = coords
            marker_type = props.get("markerType", "")
            icon_color = "green" if marker_type == "current" else "red" if marker_type == "predicted" else "blue"
            tail = props.get("tail_number")
            speed = props.get("speed")
            popup_text = f"Tail: {tail} | Speed: {speed} m/s"
            if props.get("compliance"):
                popup_text += f"<br>{props.get('compliance')}"
            folium.Marker(
                location=[lat_pt, lon_pt],
                icon=folium.Icon(color="white", icon_color=icon_color, icon="plane"),
                popup=popup_text
            ).add_to(m)
        elif geom_type == "LineString":
            plane_color = props.get("planeColor", "purple")
            line_type = props.get("lineType", "")
            dash = "5, 5" if line_type == "projected" else None
            folium.PolyLine(
                locations=[[c[1], c[0]] for c in coords],
                color=plane_color,
                weight=3,
                dash_array=dash
            ).add_to(m)
    
    # Add historical point markers with timestamp tooltips
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
    
    # Add circle markers for flagged incursion events
    for event in flagged_events:
        folium.Circle(
            location=[event["lat"], event["lon"]],
            radius=50,  # radius in meters; adjust as needed
            color="yellow",
            fill=True,
            fill_color="yellow",
            fill_opacity=0.35,
            # Popup text when clicking the circle
            popup=(
                f"Flagged incursion for plane {event['tail']} (ref: {event['ref']})<br>"
                f"First occurred at timestamp {event['timestamp']}<br>"
                f"{event['message']}"
            ),
            # Tooltip text when hovering over the circle
            tooltip=f"Timestamp: {event['timestamp']}"
        ).add_to(m)
    
    folium.LayerControl().add_to(m)
    return m

def map_flight_identifier(flight_name: str) -> str:
    """
    Maps ATC flight names to their ADS-B tail identifiers.
    Adjust the mapping as necessary.
    """
    mapping = {
        "Southwest 2504": "SWA2504",
        "FlexJet 560": "LXJ560"
    }
    for key, ident in mapping.items():
        if key in flight_name:
            return ident
    return flight_name  # Fallback if no mapping is found

# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------
def main():
    # Sample instruction set for compliance
    instructions = [
        {
            "plane": "Southwest 2504",
            "instr": "CLEARED_TO_LAND",
            "reference": "31C",
            "time": 1740494856.48+5
        },
        {
            "plane": "FlexJet 560",
            "instr": "TURN_LEFT",
            "reference": "4L",
            "time": 1740494867.06+5
        },
        {
            "plane": "FlexJet 560",
            "instr": "CLEAR_TO_CROSS",
            "reference": "31L",
            "time": 1740494867.06+5
        },
        {
            "plane": "FlexJet 560",
            "instr": "HOLD_SHORT",
            "reference": "31C",
            "time": 1740494867.06+5
        },
        {
            "plane": "FlexJet 560",
            "instr": "HOLD_POSITION",
            "reference": "",
            "time": 1740494913.54+5
        },
        {
            "plane": "FlexJet 560",
            "instr": "HOLD_POSITION",
            "reference": "",
            "time": 1740494915.44+5
        },
        {
            "plane": "FlexJet 560",
            "instr": "HOLD_SHORT",
            "reference": "Hotel",
            "time": 1740494919.82+5
        },
        {
            "plane": "FlexJet 560",
            "instr": "HOLD_SHORT",
            "reference": "Hotel",
            "time": 1740494922.54+5
        },
        {
            "plane": "Southwest 2504",
            "instr": "TURN_LEFT_HEADING",
            "reference": "220",
            "time": 1740494932.7+5
        },
        {
            "plane": "FlexJet 560",
            "instr": "HOLD_POSITION",
            "reference": "",
            "time": 1740494939.96+5
        },
        {
            "plane": "FlexJet 560",
            "instr": "HOLD_POSITION",
            "reference": "",
            "time": 1740494941.3+5
        }
    ]
    
    # 1) Load static airport data
    gdf_edges = assimilate_routes()
    center_lat, center_lon, static_feats = generate_static_features(gdf_edges)
    
    # 2) Load full ADS-B data for each plane, up to a chosen timestamp
    tracker = AircraftTracker(folder_path="adsb/csvs")
    query_ts = 1740500135  # adjust as needed
    plane_histories = {}
    for tail, df in tracker.aircraft_data.items():
        subset = df[(df["Timestamp"] <= query_ts) & (df["Timestamp"] >= 1740494856)]
        if not subset.empty:
            plane_histories[tail] = subset
    
    # 3) Compute time window based on Southwest flight's arrival at Chicago Midway and last ATC command
    last_atc_time = max(instr["time"] for instr in instructions)
    southwest_tail = map_flight_identifier("Southwest 2504")
    arrival_time = None
    if southwest_tail in plane_histories:
        df_sw = plane_histories[southwest_tail].sort_values("Timestamp")
        # Determine arrival as the first instance within 1 km of airport center
        for _, row in df_sw.iterrows():
            if distance((row["lat"], row["lon"]), (center_lat, center_lon)).meters < 1000:
                arrival_time = row["Timestamp"]
                break
    if arrival_time is None and southwest_tail in plane_histories:
        arrival_time = plane_histories[southwest_tail]["Timestamp"].min()
    
    # Define window with a 2-minute (120 sec) buffer before arrival and after last ATC command
    window_start = arrival_time - 60
    window_end = last_atc_time + 60

    # Filter each flight's history to only include records within the computed time window
    for tail, df in plane_histories.items():
        plane_histories[tail] = df[(df["Timestamp"] >= window_start) & (df["Timestamp"] <= window_end)]
    
    # 4) Log flagged incursions (only first occurrence per plane/instruction)
    flagged_events = log_flagged_incursions(plane_histories, instructions, static_feats, interval=60)
    
    # 5) Build flight path GeoJSON (including compliance info)
    flight_geojson = build_flight_path_geojson(
        plane_histories=plane_histories,
        instructions=instructions,
        static_features=static_feats,
        interval=60  # Predict 60 seconds ahead
    )
    
    # 6) Construct and save the interactive Folium map
    folium_map = build_interactive_map(center_lat, center_lon, static_feats, flight_geojson, plane_histories, flagged_events)
    folium_map.save("kmdw_interactive_flight_map.html")
    print("Interactive map saved to kmdw_interactive_flight_map.html")
    print("\nNote on flagged incursions: Repeated flagging over long periods may occur if compliance is evaluated on every record. We now only record the first flagged event per plane/instruction.")

if __name__ == "__main__":
    main()
