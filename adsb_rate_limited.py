import time
import requests
from math import radians, cos, sin, sqrt, atan2, atan, degrees

# OpenSky API endpoint for getting state vectors
url = "https://opensky-network.org/api/states/all"

# Function to calculate distance between two lat/lon points using the Haversine formula
def haversine(lat1, lon1, lat2, lon2):
    R = 3958.8  # Radius of Earth in miles
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2)**2 + cos(lat1) * cos(lat2) * sin(dlon / 2)**2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c

# Cache variables
cache = None
cache_time = 0
CACHE_DURATION = 60 * 5  # 5 minutes

# Boston's latitude and longitude
boston_lat = 42.3601
boston_lon = -71.0589

# Function to calculate pitch from the 3D velocity components
def calculate_pitch(velocity):
    # Check if velocity is a valid 3D vector
    if isinstance(velocity, list) and len(velocity) == 3:
        # Velocity components (velocity[0] = north/south, velocity[1] = east/west, velocity[2] = vertical)
        vx, vy, vz = velocity
        if vx == 0 and vy == 0:  # Avoid division by zero if there's no horizontal velocity
            return 0  # Plane is either perfectly level or moving vertically only
        pitch = atan(vz / sqrt(vx**2 + vy**2))
        return degrees(pitch)  # Convert radians to degrees
    return 0  # Return 0 if velocity is not valid

# Function to get planes near Boston
def get_planes_near_boston():
    global cache, cache_time
    
    current_time = time.time()
    
    # Check if cache is still valid (5 minutes)
    if cache and current_time - cache_time < CACHE_DURATION:
        print("Using cached data...")
        return cache
    
    try:
        # Make the request without authentication for anonymous access
        response = requests.get(url)
        
        # Check the response status code
        if response.status_code != 200:
            print(f"Error: Unable to fetch data (Status code: {response.status_code})")
            return []
        
        # Parse the JSON response
        data = response.json()
        
        # Check if the 'states' field is in the response
        if 'states' not in data:
            print("Error: 'states' not found in response.")
            return []
        
        states = data['states']
        
        # Filter planes based on distance from Boston (50-mile radius)
        nearby_planes = []
        for plane in states:
            lat = plane[6]  # Latitude is at index 6
            lon = plane[5]  # Longitude is at index 5
            on_ground = plane[8]  # On ground status is at index 8
            velocity = plane[9]  # Velocity vector is at index 9
            heading = plane[10]  # Heading (yaw) is at index 10
            
            if lat is not None and lon is not None:  # Check if coordinates are valid
                distance = haversine(boston_lat, boston_lon, lat, lon)
                
                if distance <= 50:  # Select planes within 50 miles
                    pitch = calculate_pitch(velocity)  # Calculate pitch from velocity
                    
                    nearby_planes.append({
                        'icao24': plane[0],
                        'callsign': plane[1],
                        'country': plane[2],
                        'latitude': lat,
                        'longitude': lon,
                        'altitude': plane[7],  # Barometric altitude is at index 7
                        'on_ground': on_ground,  # Whether the plane is on the ground
                        'pitch': pitch,  # Pitch in degrees
                        'yaw': heading,  # Yaw in degrees
                    })
        
        # Cache the results
        cache = nearby_planes
        cache_time = current_time
        
        return nearby_planes
    
    except Exception as e:
        print(f"Error: {e}")
        return []

# Retrieve and print the nearby planes with pitch and yaw
nearby_planes = get_planes_near_boston()
if nearby_planes:
    print("Planes within 50 miles of Boston:")
    for plane in nearby_planes:
        print(f"ICAO24: {plane['icao24']}, Callsign: {plane['callsign']}, "
              f"Country: {plane['country']}, Latitude: {plane['latitude']}, "
              f"Longitude: {plane['longitude']}, Altitude: {plane['altitude']} ft, "
              f"On Ground: {'Yes' if plane['on_ground'] else 'No'}, "
              f"Pitch: {plane['pitch']:.2f} degrees, Yaw: {plane['yaw']:.2f} degrees")
else:
    print("No planes found within 50 miles of Boston.")


#do research to find out the trail for the 2 planes in the link w/ all relevant ADSB data, need to get past times



