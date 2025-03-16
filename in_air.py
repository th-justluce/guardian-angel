import requests
import math
import time
import matplotlib.pyplot as plt
from typing import Dict, Optional, List

#############################
# Helper Functions
#############################

def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Returns approximate great-circle distance in nautical miles between two
    latitude/longitude points using the haversine formula.
    """
    R = 3440.0  # Earth radius in nautical miles
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (math.sin(dphi / 2)**2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def feet_to_nm(feet):
    """ Convert feet to nautical miles. """
    return feet / 6076.12

def compute_2d_velocity(ground_speed_knots, track_degrees):
    """
    Convert ground speed (knots) and track (degrees from north) into an (vx, vy) vector in NM/s.
    1 knot = 1 NM/h;  so  ground_speed_knots / 3600 => NM/s
    """
    speed_nm_s = ground_speed_knots / 3600.0
    theta = math.radians(track_degrees)  # track from north, clockwise
    vx = speed_nm_s * math.sin(theta)
    vy = speed_nm_s * math.cos(theta)
    return vx, vy

#############################
# Aircraft Class
#############################

class Aircraft:
    def __init__(self, raw_data: dict):
        self.hex = raw_data.get("hex")
        self.flight = raw_data.get("flight", "").strip()
        self.update(raw_data)

    def update(self, raw_data: dict):
        self.lat = raw_data.get("lat")
        self.lon = raw_data.get("lon")
        
        alt_baro = raw_data.get("alt_baro")
        if isinstance(alt_baro, int):
            self.altitude_ft = alt_baro
        else:
            self.altitude_ft = 0  # if 'ground' or missing, assume 0
        
        self.ground_speed_knots = raw_data.get("gs", 0.0)
        # prefer "track" if present, fallback to "true_heading"
        self.track_deg = raw_data.get("track") or raw_data.get("true_heading") or 0.0
        self.vertical_rate_fpm = raw_data.get("baro_rate", 0.0)

    def is_on_ground(self) -> bool:
        return self.altitude_ft < 50

    def distance_nm_to(self, other: "Aircraft") -> float:
        """ Approximate 3D distance in nautical miles. """
        if (self.lat is None or self.lon is None or
            other.lat is None or other.lon is None):
            return float("inf")
        
        horiz_dist_nm = haversine_distance(self.lat, self.lon, other.lat, other.lon)
        vert_dist_nm = feet_to_nm(abs(self.altitude_ft - other.altitude_ft))
        return math.sqrt(horiz_dist_nm**2 + vert_dist_nm**2)

    def time_to_possible_collision(
        self, other: "Aircraft", collision_radius_nm: float = 0.2
    ) -> Optional[float]:
        # Very simplified approach: see the previous explanation for details.
        alt_diff_ft = abs(self.altitude_ft - other.altitude_ft)
        allowed_vertical_ft = 50 if (self.is_on_ground() and other.is_on_ground()) else 1000
        if alt_diff_ft > allowed_vertical_ft:
            return None
        
        vx1, vy1 = compute_2d_velocity(self.ground_speed_knots, self.track_deg)
        vx2, vy2 = compute_2d_velocity(other.ground_speed_knots, other.track_deg)

        # Current positions (approx):
        if (self.lat is None or self.lon is None or
            other.lat is None or other.lon is None):
            return None
        
        avg_lat = (self.lat + other.lat) / 2.0
        lat_diff_deg = other.lat - self.lat
        lon_diff_deg = other.lon - self.lon
        dx_nm = lon_diff_deg * math.cos(math.radians(avg_lat)) * 60.0
        dy_nm = lat_diff_deg * 60.0
        
        rvx = vx2 - vx1
        rvy = vy2 - vy1

        A = rvx**2 + rvy**2
        B = 2*(dx_nm*rvx + dy_nm*rvy)
        C = dx_nm**2 + dy_nm**2 - collision_radius_nm**2

        if A < 1e-9:
            # Very slow relative motion
            horiz_dist_nm = math.sqrt(dx_nm**2 + dy_nm**2)
            if horiz_dist_nm <= collision_radius_nm:
                return 0.0
            else:
                return None

        disc = B*B - 4*A*C
        if disc < 0:
            return None
        
        sqrt_disc = math.sqrt(disc)
        t1 = (-B + sqrt_disc) / (2*A)
        t2 = (-B - sqrt_disc) / (2*A)
        times = [t for t in (t1, t2) if t >= 0]
        if not times:
            return None
        
        collision_time_s = min(times)  # This is in hours if our velocities are nm/s. Actually, we used nm/s, so time is in seconds already
        return collision_time_s

#############################
# ADSBManager Class
#############################

class ADSBManager:
    def __init__(self, endpoint: str):
        self.endpoint = endpoint
        self.aircrafts: Dict[str, Aircraft] = {}

    def fetch_data(self):
        try:
            response = requests.get(self.endpoint, timeout=10)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            print(f"Error fetching ADS-B data: {e}")
            return
        
        for plane in data.get("ac", []):
            hex_id = plane.get("hex")
            if not hex_id:
                continue
            if hex_id not in self.aircrafts:
                self.aircrafts[hex_id] = Aircraft(plane)
            else:
                self.aircrafts[hex_id].update(plane)

    def check_collisions(self, selected_hex: str, alert_time_s: float = 60.0):
        if selected_hex not in self.aircrafts:
            print(f"Selected aircraft '{selected_hex}' not in manager.")
            return
        
        primary_ac = self.aircrafts[selected_hex]

        for hex_id, other_ac in self.aircrafts.items():
            if hex_id == selected_hex:
                continue
            ttc = primary_ac.time_to_possible_collision(other_ac)
            if ttc is not None and ttc <= alert_time_s:
                dist_now = primary_ac.distance_nm_to(other_ac)
                print(f"** ALERT ** Potential collision with {other_ac.flight} "
                      f"(hex={other_ac.hex}) in ~{ttc:.1f}s. Current distance ~{dist_now:.2f} NM.")
    
    def get_aircraft_list(self) -> List[Aircraft]:
        return list(self.aircrafts.values())

#############################
# Adding a VISUAL
#############################

def visualize_aircraft(aircraft_list: List[Aircraft]):
    """
    Simple matplotlib 2D scatter plot of aircraft lat/lon and velocity arrows.
    """
    plt.clf()  # Clear the current figure
    
    # Gather valid positions
    valid_ac = [ac for ac in aircraft_list if ac.lat is not None and ac.lon is not None]
    if not valid_ac:
        plt.title("No valid aircraft data to display.")
        plt.pause(0.01)
        return
    
    lats = [ac.lat for ac in valid_ac]
    lons = [ac.lon for ac in valid_ac]
    # Plot positions
    plt.scatter(lons, lats, marker='o', color='blue')

    # Optionally, draw velocity vectors (scaled for visibility)
    for ac in valid_ac:
        vx, vy = compute_2d_velocity(ac.ground_speed_knots, ac.track_deg)
        # Convert velocity from nm/s to deg offsets so we can scale on the map:
        # 1 deg lat ~ 60 nm, 1 deg lon ~ 60 nm * cos(lat).
        # So 1 nm => ~1/60 deg lat
        scale_factor = 3000  # This factor is arbitrary for an on-screen arrow length
        delta_lon = vx * scale_factor / (60.0 * math.cos(math.radians(ac.lat)))
        delta_lat = vy * scale_factor / 60.0
        
        plt.arrow(ac.lon, ac.lat, delta_lon, delta_lat,
                  width=0.0001, color='red', alpha=0.5,
                  length_includes_head=True, head_width=0.002)
        
        # Label each aircraft with its flight or hex code
        label = ac.flight if ac.flight else ac.hex
        plt.text(ac.lon, ac.lat, label, fontsize=8, color='black')

    # Adjust plot bounds a bit
    plt.xlabel("Longitude")
    plt.ylabel("Latitude")
    plt.title("Live ADS-B Positions")
    plt.grid(True)

    # Auto-scale
    plt.axis('equal')  # so lat/lon scale equally
    plt.pause(0.01)  # brief pause to update the figure

#############################
# Example usage
#############################

if __name__ == "__main__":
    import sys
    
    # Turn on interactive mode so the figure updates in real time
    plt.ion()
    
    endpoint_url = "https://api.adsb.lol/v2/lat/42.3555/lon/-71.0565/dist/10"
    manager = ADSBManager(endpoint_url)
    
    # If known, specify the hex you want to track for collisions
    selected_aircraft_hex = "a11f59"  # e.g., one from your data snippet
    
    # Simple loop: fetch data, do collision check, visualize
    try:
        while True:
            manager.fetch_data()
            manager.check_collisions(selected_aircraft_hex, alert_time_s=60.0)
            visualize_aircraft(manager.get_aircraft_list())
            time.sleep(5)
    except KeyboardInterrupt:
        print("Exiting...")
        sys.exit(0)
