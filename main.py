import sys
from typing import Dict, List

import osmnx as ox
import pandas as pd
import geopandas as gpd

from geopy.distance import distance
from shapely.geometry import LineString

import folium

def assimilate_routes() -> gpd.GeoDataFrame:
    airport_icao_code = "KMDW"
    osm_filter = '["aeroway"~"runway|taxiway|apron|control_tower|control_center|gate|hangar|helipad|heliport|navigationaid|taxilane|terminal|windsock|highway_strip|parking_position|holding_position|airstrip|stopway|tower"]'
    G = ox.graph_from_place(
        airport_icao_code,
        simplify=False,
        retain_all=True,
        truncate_by_edge=True,
        custom_filter=osm_filter,
    )

    # Convert the graph to GeoDataFrame and return
    _, gdf_edges = ox.graph_to_gdfs(G)
    return gdf_edges

def generate_map(edges: gpd.GeoDataFrame):
    # Classify runways vs. taxiways
    #   a) If 'service' indicates 'runway' or 'taxiway'
    #   b) Otherwise, fall back to 'ref' patterns (slash in 'ref' -> runway, else taxiway)
    if 'service' in edges.columns and (
        'runway' in edges['service'].unique() or 'taxiway' in edges['service'].unique()
    ):
        runways = edges[edges['service'] == 'runway'].copy()
        taxiways = edges[edges['service'] == 'taxiway'].copy()
    else:
        # Fallback: treat any 'ref' containing '/' as a runway
        edges['ref'] = edges['ref'].fillna('')
        runways = edges[edges['ref'].str.contains('/')].copy()
        taxiways = edges[~edges['ref'].str.contains('/')].copy()

    # Buffer path geometries if width is defined as an attribute (runways often have it, taxiways sometimes do)
    def buffer_features(gdf: gpd.GeoDataFrame):
        if 'width' in gdf.columns and not gdf['width'].isna().all():
            # Project to a meter-based coordinate system
            gdf_m = gdf.to_crs(epsg=3857)
            # Buffer by half the width
            gdf_m['geometry'] = gdf_m.apply(
                lambda x: x.geometry.buffer(float(x.width) / 2, cap_style=3) if not pd.isna(x.width) else x.geometry,
                axis=1
            )
            # Convert back to WGS84
            return gdf_m.to_crs(epsg=4326)
        else:
            return gdf

    runways = buffer_features(runways)
    taxiways = buffer_features(taxiways)

    # 5. Determine a suitable map center
    if not runways.empty:
        center_lat = runways.geometry.centroid.y.mean()
        center_lon = runways.geometry.centroid.x.mean()
    elif not taxiways.empty:
        center_lat = taxiways.geometry.centroid.y.mean()
        center_lon = taxiways.geometry.centroid.x.mean()
    else:
        # Fallback: approximate center of KBOS
        print("WE FELL BACK TO HARDCODED VALUES, CHECK THE CODE...")
        # NOT GREAT
        center_lat, center_lon = 42.364, -71.005
    
    features = [runways, taxiways]

    return center_lat, center_lon, features

def build_interface(center_lat: float, center_lon: float, features: List[gpd.GeoDataFrame]):
    runways = features[0]
    taxiways = features[1]

    m = folium.Map(location=[center_lat, center_lon], zoom_start=16, tiles="cartodbpositron")

    # Add runways layer (in red)
    if not runways.empty:
        folium.GeoJson(
            runways.__geo_interface__,
            name="Runways",
            style_function=lambda feature: {
                'color': 'red',
                'weight': 3,
                'fillColor': 'red',
                'fillOpacity': 0.5,
            },
            tooltip=folium.GeoJsonTooltip(fields=['ref', 'width'], aliases=['Ref', 'Width'])
        ).add_to(m)

    # Add taxiways layer (in blue)
    if not taxiways.empty:
        folium.GeoJson(
            taxiways.__geo_interface__,
            name="Taxiways",
            style_function=lambda feature: {
                'color': 'blue',
                'weight': 2,
                'fillColor': 'blue',
                'fillOpacity': 0.5,
            },
            tooltip=folium.GeoJsonTooltip(fields=['ref', 'width'], aliases=['Ref', 'Width'])
        ).add_to(m)

    folium.LayerControl().add_to(m)
    return m

def predict_position(lat, lon, bearing, speed, t):
    """
    Predict the future position given the current location, bearing, speed, and time.
    """
    d = speed * t
    origin = (lat, lon)
    destination = distance(meters=d).destination(origin, bearing)
    return destination.latitude, destination.longitude

def evaluate_compliance(instructions: List[Dict], plane: str,
                        current_lat, current_lon, predicted_lat, predicted_lon,
                        speed, features, simulation_time: float) -> str:
    """
    Evaluate compliance with the most recent instruction for the given plane whose timestamp
    is <= simulation_time. For the instruction, check if the predicted path intersects
    the feature (runway or taxiway) with the matching 'ref'. Then compare the command
    with the aircraft's state.
    """
    # Filter instructions for the given plane and time
    relevant_instr = [instr for instr in instructions if instr["plane"] == plane and instr["time"] <= simulation_time]
    if not relevant_instr:
        return "No active instruction for compliance evaluation."

    # Use the instruction with the latest time stamp
    current_instr = max(relevant_instr, key=lambda x: x["time"])
    instr_ref = current_instr["reference"]
    command = current_instr["command"]

    # Build the projected path as a LineString
    line = LineString([(current_lon, current_lat), (predicted_lon, predicted_lat)])
    # Try to find the feature with matching 'ref'
    found_feature = None
    for feature_group in features:
        for idx, row in feature_group.iterrows():
            ref_val = str(row.get("ref", "")).strip()
            if ref_val == instr_ref:
                found_feature = row.geometry
                break
        if found_feature is not None:
            break

    if found_feature is None:
        return f"Instruction {current_instr} has no matching feature on the map."

    intersects = line.intersects(found_feature)
    # Set some thresholds (these values are illustrative)
    landing_max_speed = 25.0      # m/s allowed for landing clearance
    crossing_min_speed = 5.0      # m/s minimum speed expected when cleared to cross
    hold_speed_threshold = 1.0    # m/s: near zero expected for hold-short

    compliance = ""
    if command == "CLEAR_TO_LAND":
        # Expectation: aircraft should intersect a runway and its speed should be moderate.
        if intersects:
            if speed <= landing_max_speed:
                compliance = f"In compliance: CLEARED TO LAND on {instr_ref} at safe speed."
            else:
                compliance = f"Non-compliant: Approaching runway {instr_ref} too fast for landing clearance."
        else:
            compliance = f"Non-compliant: Predicted path does not intersect runway {instr_ref} despite CLEAR_TO_LAND."
    elif command == "CLEAR_TO_CROSS":
        # Expectation: aircraft should be moving (above crossing_min_speed) while crossing a taxiway.
        if intersects:
            if speed >= crossing_min_speed:
                compliance = f"In compliance: CLEARED TO CROSS {instr_ref} while moving."
            else:
                compliance = f"Non-compliant: Aircraft is not moving while cleared to cross {instr_ref}."
        else:
            compliance = f"Non-compliant: Predicted path does not intersect taxiway {instr_ref} despite CLEAR_TO_CROSS."
    elif command == "HOLD_SHORT":
        # Expectation: aircraft should not intrude into the feature (or be nearly stationary if already at the hold position).
        if intersects:
            if speed <= hold_speed_threshold:
                compliance = f"In compliance: HOLD_SHORT at {instr_ref} (aircraft stationary)."
            else:
                compliance = f"Non-compliant: Aircraft is moving into {instr_ref} despite HOLD_SHORT."
        else:
            compliance = f"In compliance: No incursion of {instr_ref} as required by HOLD_SHORT."
    else:
        compliance = "Unknown command."

    # Include the instruction context in the response.
    return f"Instruction [{current_instr}] evaluation: {compliance}"

def main(args=sys.argv):
    # Simulated instruction set (parsed from ATC audio)
    instructions = [
      {
        "plane": "Southwest 2504",
        "command": "CLEAR_TO_LAND",
        "reference": "31C",
        "time": 9.48
      },
      {
        "plane": "Southwest 2504",
        "command": "CLEAR_TO_LAND",
        "reference": "31C",
        "time": 12
      },
      {
        "plane": "Flexion 560",
        "command": "CLEAR_TO_CROSS",
        "reference": "31L",
        "time": 20.06
      },
      {
        "plane": "Flexion 560",
        "command": "HOLD_SHORT",
        "reference": "31C",
        "time": 20.06
      },
      {
        "plane": "Flagship 560",
        "command": "HOLD_SHORT",
        "reference": "H1",
        "time": 75.54
      }
    ]

    # Assimilate map data
    gdf_edges = assimilate_routes()
    center_lat, center_lon, features = generate_map(gdf_edges)
    m = build_interface(center_lat, center_lon, features)

    # Placeholder values (Replace with ADS-B or GPS information)
    # Position in 3D space (x, y, z), Bearing (degrees), Speed (m/s), Vertical Rate (m/s)
    # Going to have that for some number of aircraft, above will apply for obstacle avoidance.
    # TCAS allows planes to communicate with each other. We don't have that communication
    # Therefore, we need some other system to determine who should descend, who should climb
    current_lat, current_lon = 41.7941664, -87.7642633      # Current position at KMDW
    bearing = 90                                            # Heading (in degrees)
    speed = 50                                              # Speed in m/s
    simulation_time = 75                                    # seconds into simulation

    predicted_lat, predicted_lon = predict_position(current_lat, current_lon, bearing, speed, simulation_time)
    
    # For simulation, assume this aircraft is "Southwest 2504"
    current_plane = "Southwest 2504"
    compliance_msg = evaluate_compliance(instructions, current_plane,
                                         current_lat, current_lon,
                                         predicted_lat, predicted_lon,
                                         speed, features, simulation_time)

    # Mark current position
    folium.Marker(
        [current_lat, current_lon],
        popup="Current Position",
        icon=folium.Icon(color="green"),
        tooltip=f"[Lat: {current_lat}, Long: {current_lon}]"
    ).add_to(m)
    print(f"[DEBUG] Marker for current position should be inserted.\n")

    # Mark predicted position with incursion and compliance information
    folium.Marker(
        [predicted_lat, predicted_lon],
        popup=f"Predicted Position (t={simulation_time}s).\nCompliance: {compliance_msg}",
        icon=folium.Icon(color="red"),
        tooltip=f"[Lat: {predicted_lat}, Long: {predicted_lon}]",
    ).add_to(m)
    print(f"[DEBUG] Marker for predicted position should be inserted.\n")

    # Draw projected path polyline
    folium.PolyLine(
        locations=[[current_lat, current_lon], [predicted_lat, predicted_lon]],
        color="yellow",
        weight=25,
        opacity=0.8
    ).add_to(m)
    print(f"[DEBUG] Path prediction should be drawn.\n")

    m.save("kmdw-pathpreds.html")
    print(compliance_msg)

if __name__ == "__main__":
    main()