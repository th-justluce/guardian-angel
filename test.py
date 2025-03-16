import time
import requests
from math import radians, cos, sin, sqrt, atan2
import numpy as np
import matplotlib.pyplot as plt

url = "https://api.adsb.lol/v2/lat/42.3555/lon/-71.0565/dist/50"

def haversine(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return None
    
    R = 3958.8
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2)**2 + cos(lat1) * cos(lat2) * sin(dlon / 2)**2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c

def calculate_vertical_distance(plane1, plane2):
    if plane1['altitude'] is None or plane2['altitude'] is None:
        return None
    return abs(plane1['altitude'] - plane2['altitude'])

def extrapolate_position(plane, seconds=1):
    if plane['velocity'] is None or plane['track'] is None:
        return plane['latitude'], plane['longitude']
    
    velocity_per_second = plane['velocity'] / 3600.0
    delta_lat = velocity_per_second * cos(radians(plane['track'])) / 69.0
    delta_lon = velocity_per_second * sin(radians(plane['track'])) / (69.0 * cos(radians(plane['latitude'])))
    
    new_lat = plane['latitude'] + delta_lat * seconds
    new_lon = plane['longitude'] + delta_lon * seconds
    
    return new_lat, new_lon

def find_plane_pairs_below_350(planes, max_distance=100, max_vertical_distance=2000):
    plane_pairs_below_350 = []
    all_plane_pairs = []
    
    for i, plane in enumerate(planes):
        for j in range(i + 1, len(planes)):
            other_plane = planes[j]
            
            if plane['velocity'] is None or other_plane['velocity'] is None:
                continue
            
            if plane['altitude'] is None or other_plane['altitude'] is None:
                continue
            
            horizontal_distance = haversine(plane['latitude'], plane['longitude'], other_plane['latitude'], other_plane['longitude'])
            
            if horizontal_distance is not None:
                vertical_distance = calculate_vertical_distance(plane, other_plane)
                
                all_plane_pairs.append((plane['icao24'], other_plane['icao24'], horizontal_distance, vertical_distance))
                
                if horizontal_distance <= max_distance and (vertical_distance is None or vertical_distance <= max_vertical_distance):
                    plane_pairs_below_350.append((plane['icao24'], other_plane['icao24'], horizontal_distance, vertical_distance))
    
    return plane_pairs_below_350, all_plane_pairs

def get_planes_near_location():
    try:
        print("Fetching plane data...")
        response = requests.get(url)
        
        if response.status_code != 200:
            print(f"Error: Unable to fetch data (Status code: {response.status_code})")
            return []
        
        data = response.json()
        
        if 'ac' not in data:
            print("Error: 'ac' not found in the response.")
            return []
        
        planes = []
        for plane in data['ac']:
            lat, lon = plane.get('lat'), plane.get('lon')
            altitude = plane.get('alt_baro', None)
            velocity = plane.get('gs', None)
            callsign = plane.get('flight', None)
            origin_country = plane.get('origin_country', None)
            
            if None in (lat, lon, velocity, altitude):
                continue
            
            try:
                altitude = float(altitude) if altitude is not None else None
            except ValueError:
                altitude = None

            try:
                velocity = float(velocity) if velocity is not None else None
            except ValueError:
                velocity = None

            on_ground = True if altitude is not None and altitude < 50 else False
            pitch = plane.get('pitch', None)
            yaw = plane.get('yaw', None)
            true_heading = plane.get('trkh', 0)
            track = plane.get('track', 0)
            
            if true_heading is None:
                true_heading = 0
            if track is None:
                track = 0

            yaw = (true_heading - track) % 360
            pitch = atan2(altitude, velocity) if altitude and velocity else None

            if altitude is not None and isinstance(altitude, (int, float)):
                if altitude < 15240:
                    altitude = altitude * 3.28084
                else:
                    altitude = None
            if callsign is None or altitude is None:
                continue

            plane_data = {
                'icao24': plane['hex'],
                'latitude': lat,
                'longitude': lon,
                'altitude': altitude,
                'velocity': velocity,
                'callsign': callsign,
                'origin_country': origin_country,
                'on_ground': on_ground,
                'track': track,
                'pitch': pitch,
                'yaw': yaw
            }
            planes.append(plane_data)

        return planes

    except Exception as e:
        print(f"Error: {e}")
        return []

nearby_planes = get_planes_near_location()
if nearby_planes:
    print("Processing plane pairs...")

    # Initialize list to store data for the plot after 30 seconds
    all_plane_pairs = []

    for second in range(1, 31):  # Simulate 30 seconds
        print(f"Second: {second}")

        # Extrapolate plane positions
        for plane in nearby_planes:
            plane['latitude'], plane['longitude'] = extrapolate_position(plane, seconds=1)

        # Find plane pairs at this second
        plane_pairs_below_350, _ = find_plane_pairs_below_350(nearby_planes, max_distance=100, max_vertical_distance=350)

        # Add valid pairs to the list
        all_plane_pairs.extend(plane_pairs_below_350)

    # After processing all 30 seconds, plot the results
    if all_plane_pairs:
        print(f"Found {len(all_plane_pairs)} pairs within the distance limits.")

        fig = plt.figure(figsize=(12, 6))
        ax = fig.add_subplot(111, projection='3d')

        x_pos = np.arange(len(all_plane_pairs))
        y_pos = np.zeros(len(all_plane_pairs))
        z_pos = np.zeros(len(all_plane_pairs))

        z_height = [pair[3] for pair in all_plane_pairs]

        separation = 1.5
        x_pos_separated = [x * separation for x in x_pos]

        ax.bar3d(x_pos_separated, y_pos, z_pos, 1, 1, z_height, color='red', shade=True)

        ax.set_zlim(0, max(z_height))
        ax.set_xticks(x_pos_separated)
        ax.set_xticklabels([f"{pair[0]} - {pair[1]}" for pair in all_plane_pairs], rotation=45, ha="right", fontsize=8)

        ax.set_ylabel('Horizontal Distance (miles)')
        ax.set_zlabel('Vertical Distance (feet)')
        ax.set_title('Planes with Vertical Distance Below 350 Feet')

        plt.tight_layout()
        plt.show()

else:
    print("No planes found within 50 miles of the location.")

