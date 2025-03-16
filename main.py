from adsb.adsb_manager import AircraftTracker

from control.features import assimilate_routes, generate_static_features
from control.flights import Flights
from control.visualize import build_animated_map

from geopy.distance import distance

def log_violations(incursions: dict):
    print(f"\nNature of incursions (set length: {len(incursions)}):")
    print("----------------------------------------------------------------------------------------------------------------")
    for _, val in incursions.items():
        reason = val.get('message')
        toi = val.get('timestamp')
        speed = val.get('speed')
        heading = val.get('heading')
        forecast = val.get('interval')
        recommendation = val.get('advisory')
        pred_outcome = val.get('prediction')

        print(f">> {reason}\n::::::::::::::::: [ timestamp: {toi} • lat/long location: ({val.get('lat'), val.get('lon')})")
        print(f"::::::::::::::::: [ speed: {speed}ms/s • heading: {heading} degrees • path forecast: {forecast} seconds")
        print(f"::::::::::::::::: |--------------------------------------------------------------------------------------")
        print(f"::::::::::::::::: |     RECOMMENDATION : {recommendation}")
        print(f"::::::::::::::::: |     IF NOT FOLLOWED: {pred_outcome}")
        print(f"::::::::::::::::: |--------------------------------------------------------------------------------------")
        print("------------------^---------------------------------------------------------------------------------------------")
    print("\nInteractive map saved to kmdw_interactive_flight_map.html")

def main():
    # ATC tower instructions: Audio processed through Whisper and transcribed into JSON object for ADS-B referencing
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
    plane_histories = {}
    query_ts = 0
    for tail, df in tracker.aircraft_data.items():
        if max(df["Timestamp"]) > query_ts:
            query_ts = max(df["Timestamp"])
        subset = df[df["Timestamp"] <= query_ts]
        if not subset.empty:
            plane_histories[tail] = subset
    
    # Initialize a time buffer between the first and last ATC instructions
    forced_start = 1740494856 - 15
    forced_end = 1740494920 + 15
    
    for tail, df in plane_histories.items():
        plane_histories[tail] = df[(df["Timestamp"] >= forced_start)]
    # for tail, df in plane_histories.items():
    #     plane_histories[tail] = df[(df["Timestamp"] <= forced_end)]
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
    
    # 3) Log flagged incursions (only the first occurrence per plane/ref)
    flagged_events = flights.log_flagged_incursions(plane_histories, instructions, static_feats, interval=30)
    
    # 4) Build flight path GeoJSON (including optional compliance checks)
    flight_geojson = flights.build_flight_path_geojson(plane_histories, instructions, static_feats, interval=30)
    
    # 5) Create and save the interactive map
    folium_map = build_animated_map(
        center_lat, center_lon,
        static_feats,
        flight_geojson,
        plane_histories,
        flagged_events,
        animation_speed=50.0  # e.g. double speed
    )
    folium_map.save("kmdw_interactive_flight_map.html")

    FLAGGED_INCURSIONS = flights._getFlaggedIncursions()
    log_violations(FLAGGED_INCURSIONS)

if __name__ == "__main__":
    main()
