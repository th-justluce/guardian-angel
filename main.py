from adsb.adsb_manager import AircraftTracker

from control.features import assimilate_routes, generate_static_features
from control.flights import Flights
from control.visualize import build_interactive_map

from geopy.distance import distance

import json

def main():
    # Sample ATC instructions
    instructions = [
        {"plane": "Southwest 2504", "instr": "CLEARED_TO_LAND", "reference": "31C", "time": 1740494856.48},
        {"plane": "FlexJet 560", "instr": "TURN_LEFT", "reference": "04L/22R", "time": 1740494867.06},
        {"plane": "FlexJet 560", "instr": "CLEAR_TO_CROSS", "reference": "13C/31C", "time": 1740494867.06},
        {"plane": "FlexJet 560", "instr": "HOLD_SHORT", "reference": "13C/31C", "time": 1740494867.06},
        {"plane": "FlexJet 560", "instr": "HOLD_POSITION", "reference": "", "time": 1740494913.54},
        {"plane": "FlexJet 560", "instr": "HOLD_POSITION", "reference": "", "time": 1740494915.44},
        {"plane": "FlexJet 560", "instr": "HOLD_SHORT", "reference": "H", "time": 1740494919.82},
        {"plane": "FlexJet 560", "instr": "HOLD_SHORT", "reference": "H", "time": 1740494922.54},
        {"plane": "Southwest 2504", "instr": "TURN_LEFT_HEADING", "reference": "220", "time": 1740494932.7},
        {"plane": "FlexJet 560", "instr": "HOLD_POSITION", "reference": "", "time": 1740494939.96},
        {"plane": "FlexJet 560", "instr": "HOLD_POSITION", "reference": "", "time": 1740494941.3}
    ]
    
    # 1) Load static airport data and process features
    edges = assimilate_routes()
    center_lat, center_lon, static_feats = generate_static_features(edges)
    
    # 2) Load ADS-B data for each plane
    tracker = AircraftTracker(folder_path="adsb/csvs")
    query_ts = 1740500135  # Adjust timestamp as needed
    plane_histories = {}
    for tail, df in tracker.aircraft_data.items():
        subset = df[(df["Timestamp"] <= query_ts) & (df["Timestamp"] >= 1740494856)]
        if not subset.empty:
            plane_histories[tail] = subset

    # 3) Determine the time window for evaluation based on arrival and ATC instruction times
    last_atc_time = max(instr["time"] for instr in instructions)

    flights = Flights()

    southwest_tail = flights.map_flight_identifier("Southwest 2504")
    arrival_time = None
    if southwest_tail in plane_histories:
        for _, row in plane_histories[southwest_tail].sort_values("Timestamp").iterrows():
            if distance((row["lat"], row["lon"]), (center_lat, center_lon)).meters < 500:
                arrival_time = row["Timestamp"]
                break
        if arrival_time is None:
            arrival_time = plane_histories[southwest_tail]["Timestamp"].min()

    window_start = arrival_time - 60
    window_end   = last_atc_time + 60
    for tail, df in plane_histories.items():
        plane_histories[tail] = df[(df["Timestamp"] >= window_start) & (df["Timestamp"] <= window_end)]
    
    # 4) Log flagged incursions (only the first occurrence per plane/ref)
    flagged_events = flights.log_flagged_incursions(plane_histories, instructions, static_feats, interval=20)
    
    # 5) Build flight path GeoJSON (including optional compliance checks)
    flight_geojson = flights.build_flight_path_geojson(plane_histories, instructions, static_feats, interval=20)
    
    # 6) Create and save the interactive map
    folium_map = build_interactive_map(center_lat, center_lon, static_feats, flight_geojson, plane_histories, flagged_events)
    folium_map.save("kmdw_interactive_flight_map.html")

    FLAGGED_INCURSIONS = flights._getFlaggedIncursions()
    VIOLATIONS = []
    for _, value in FLAGGED_INCURSIONS.items():
        VIOLATIONS.append(value)
    
    print(f"\nNature of incursions (set length: {len(FLAGGED_INCURSIONS)}):")
    print("-----------------")
    val: dict
    for val in VIOLATIONS:
        reason = val.get('message')
        print(f">> {reason}\n::::::::::::::::: [timestamp: {val.get('timestamp')} • lat/long location: ({val.get('lat'), val.get('lon')})]")
        print("-----------------")
    print("\nInteractive map saved to kmdw_interactive_flight_map.html")

if __name__ == "__main__":
    main()
