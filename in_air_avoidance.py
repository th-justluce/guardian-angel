import time
import requests
from math import radians, cos, sin, sqrt, atan2
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np
import cartopy.crs as ccrs
import cartopy.feature as cfeature

# URL for ADS-B data (example endpoint)
URL = "https://api.adsb.lol/v2/lat/42.3555/lon/-71.0565/dist/50"

def haversine(lat1, lon1, lat2, lon2):
    """Compute horizontal distance (in miles) between two coordinates."""
    if None in (lat1, lon1, lat2, lon2):
        return None
    R = 3958.8  # Earth radius in miles
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2)**2 + cos(lat1) * cos(lat2) * sin(dlon / 2)**2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c

def extrapolate_position(plane, dt=1):
    """Extrapolate plane position dt seconds into the future assuming constant speed/heading."""
    if plane['velocity'] is None or plane['track'] is None:
        return plane['latitude'], plane['longitude']
    velocity_mps = plane['velocity'] / 3600.0  # miles per second
    # Approximate: one degree latitude ~ 69 miles.
    delta_lat = velocity_mps * cos(radians(plane['track'])) * dt / 69.0
    delta_lon = velocity_mps * sin(radians(plane['track'])) * dt / (69.0 * cos(radians(plane['latitude'])))
    new_lat = plane['latitude'] + delta_lat
    new_lon = plane['longitude'] + delta_lon
    return new_lat, new_lon

def get_planes_data():
    """Fetch ADS-B data and return a list of planes with key data."""
    try:
        response = requests.get(URL)
        if response.status_code != 200:
            print(f"Error fetching data: Status code {response.status_code}")
            return []
        
        data = response.json()
        if 'ac' not in data:
            print("Error: 'ac' key not found in response")
            return []
        
        planes = []
        for plane in data['ac']:
            lat = plane.get('lat')
            lon = plane.get('lon')
            altitude = plane.get('alt_baro', None)
            velocity = plane.get('gs', None)
            callsign = plane.get('flight', None)
            # Skip if any critical value is missing.
            if None in (lat, lon, altitude, velocity, callsign):
                continue
            try:
                altitude = float(altitude)
                velocity = float(velocity)
            except ValueError:
                continue
            # Convert altitude to feet if below 15,240 (assume meters), else skip unrealistic values.
            if altitude < 15240:
                altitude = altitude * 3.28084
            else:
                altitude = None
            track = plane.get('track', 0)
            plane_data = {
                'icao24': plane.get('hex', 'N/A'),
                'latitude': lat,
                'longitude': lon,
                'altitude': altitude,
                'velocity': velocity,  # in miles per hour
                'callsign': callsign,
                'track': track
            }
            planes.append(plane_data)
        return planes

    except Exception as e:
        print(f"Exception during data fetch: {e}")
        return []

def simulate_plane_trajectory(plane, simulation_time=60):
    """Simulate a plane's trajectory over a given number of seconds."""
    trajectory = []
    # Create a copy of the plane's state to avoid modifying the original data.
    current_state = plane.copy()
    for t in range(simulation_time + 1):
        trajectory.append({
            'time': t,
            'latitude': current_state['latitude'],
            'longitude': current_state['longitude'],
            'altitude': current_state['altitude']
        })
        new_lat, new_lon = extrapolate_position(current_state, dt=1)
        current_state['latitude'] = new_lat
        current_state['longitude'] = new_lon
    return trajectory

def detect_collisions(trajectories, horizontal_threshold=1.0, vertical_threshold=350):
    """
    Check for near-miss collision events between plane pairs over the simulation.
    Thresholds: horizontal_threshold in miles, vertical_threshold in feet.
    """
    collision_events = []
    plane_ids = list(trajectories.keys())
    for i in range(len(plane_ids)):
        for j in range(i + 1, len(plane_ids)):
            id1 = plane_ids[i]
            id2 = plane_ids[j]
            traj1 = trajectories[id1]
            traj2 = trajectories[id2]
            # Check each simulated time point.
            for t in range(len(traj1)):
                pos1 = traj1[t]
                pos2 = traj2[t]
                horiz_dist = haversine(pos1['latitude'], pos1['longitude'], pos2['latitude'], pos2['longitude'])
                if pos1['altitude'] and pos2['altitude']:
                    vert_dist = abs(pos1['altitude'] - pos2['altitude'])
                else:
                    vert_dist = None
                if horiz_dist is not None and vert_dist is not None:
                    if horiz_dist <= horizontal_threshold and vert_dist <= vertical_threshold:
                        collision_events.append({
                            'time': t,
                            'plane1': id1,
                            'plane2': id2,
                            'horizontal_distance': horiz_dist,
                            'vertical_distance': vert_dist,
                            'latitude': pos1['latitude'],
                            'longitude': pos1['longitude']
                        })
    return collision_events

def altitude_to_color(altitude, min_alt=0, max_alt=45000):
    """Map altitude to a color using a blue-green-yellow-red gradient."""
    if altitude is None:
        return "#808080"  # Gray for unknown altitude
    
    # Normalize altitude
    norm_alt = min(max(altitude, min_alt), max_alt) / max_alt
    
    # Create gradient: blue (low) -> green -> yellow -> red (high)
    if norm_alt < 0.25:
        # Blue to cyan
        r = 0
        g = int(255 * (norm_alt * 4))
        b = 255
    elif norm_alt < 0.5:
        # Cyan to green
        r = 0
        g = 255
        b = int(255 * (1 - (norm_alt - 0.25) * 4))
    elif norm_alt < 0.75:
        # Green to yellow
        r = int(255 * ((norm_alt - 0.5) * 4))
        g = 255
        b = 0
    else:
        # Yellow to red
        r = 255
        g = int(255 * (1 - (norm_alt - 0.75) * 4))
        b = 0
    
    return f"#{r:02x}{g:02x}{b:02x}"

def create_plane_icon(heading):
    """Create a simple plane icon pointing in the direction of heading."""
    # Convert heading to radians (0 is north, increases clockwise)
    rad_heading = np.radians(90 - heading)  # Adjust so 0 is east in the math, but north in the result
    
    # Create basic plane shape
    nose_x, nose_y = np.cos(rad_heading), np.sin(rad_heading)
    left_wing_x = 0.5 * np.cos(rad_heading + np.pi/2)
    left_wing_y = 0.5 * np.sin(rad_heading + np.pi/2)
    right_wing_x = 0.5 * np.cos(rad_heading - np.pi/2)
    right_wing_y = 0.5 * np.sin(rad_heading - np.pi/2)
    tail_x, tail_y = -0.5 * np.cos(rad_heading), -0.5 * np.sin(rad_heading)
    
    icon_x = [nose_x, left_wing_x, tail_x, right_wing_x, nose_x]
    icon_y = [nose_y, left_wing_y, tail_y, right_wing_y, nose_y]
    
    return icon_x, icon_y

def realtime_simulation():
    """Continuously update a live plot of predicted trajectories and collision warnings."""
    plt.ion()  # Enable interactive mode
    
    # Setup the map projection with Cartopy (ensures north is up)
    fig = plt.figure(figsize=(14, 10))
    ax = fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())
    
    # Add map features
    ax.add_feature(cfeature.COASTLINE, linewidth=0.5)
    ax.add_feature(cfeature.STATES, linewidth=0.3, alpha=0.5)
    ax.add_feature(cfeature.LAND, facecolor='#F5F5F5')
    ax.add_feature(cfeature.OCEAN, facecolor='#E0F0FF')
    
    # Create status display area
    status_ax = fig.add_axes([0.1, 0.01, 0.8, 0.05])
    status_ax.axis('off')
    status_text = status_ax.text(0.5, 0.5, "Initializing...", fontsize=12, 
                                ha='center', va='center', 
                                bbox=dict(boxstyle="round,pad=0.5", facecolor='white', alpha=0.8))
    
    # Create legend for altitude
    cmap_ax = fig.add_axes([0.92, 0.3, 0.02, 0.4])
    gradient = np.linspace(0, 1, 256).reshape(-1, 1)
    cmap_ax.imshow(gradient, aspect='auto', cmap='jet')
    cmap_ax.set_title('Altitude', fontsize=10)
    cmap_ax.set_xticks([])
    cmap_ax.set_yticks([0, 128, 255])
    cmap_ax.set_yticklabels(['0', '20,000', '40,000 ft'])
    
    # North arrow indicator
    north_ax = fig.add_axes([0.9, 0.9, 0.08, 0.08])
    north_ax.axis('off')
    north_ax.arrow(0.5, 0.1, 0, 0.6, head_width=0.1, head_length=0.1, 
                 fc='black', ec='black', transform=north_ax.transAxes)
    north_ax.text(0.5, 0.05, 'N', transform=north_ax.transAxes, 
                ha='center', va='center', fontsize=10, fontweight='bold')
    
    try:
        iteration = 0
        while True:
            iteration += 1
            start_time = time.time()
            
            # Fetch and process plane data
            planes = get_planes_data()
            if not planes:
                status_text.set_text("No plane data available. Retrying...")
                plt.pause(1)
                continue

            # Compute trajectories and check for collisions
            trajectories = {}
            for plane in planes:
                trajectories[plane['icao24']] = simulate_plane_trajectory(plane, simulation_time=60)

            collisions = detect_collisions(trajectories, horizontal_threshold=1.0, vertical_threshold=350)

            # Clear and update the plot
            ax.clear()
            
            # Re-add map features after clearing
            ax.add_feature(cfeature.COASTLINE, linewidth=0.5)
            ax.add_feature(cfeature.STATES, linewidth=0.3, alpha=0.5)
            ax.add_feature(cfeature.LAND, facecolor='#F5F5F5')
            ax.add_feature(cfeature.OCEAN, facecolor='#E0F0FF')
            
            # Calculate map boundaries based on all plane positions
            all_lats = []
            all_lons = []
            for traj_list in trajectories.values():
                all_lats.extend([point['latitude'] for point in traj_list])
                all_lons.extend([point['longitude'] for point in traj_list])
                
            if all_lats and all_lons:
                lat_min, lat_max = min(all_lats), max(all_lats)
                lon_min, lon_max = min(all_lons), max(all_lons)
                
                # Add a buffer
                lat_buffer = (lat_max - lat_min) * 0.2
                lon_buffer = (lon_max - lon_min) * 0.2
                ax.set_extent([lon_min - lon_buffer, lon_max + lon_buffer, 
                               lat_min - lat_buffer, lat_max + lat_buffer], 
                              crs=ccrs.PlateCarree())
            
            # Create a color map for different planes
            plane_colors = {}
            for i, plane_id in enumerate(trajectories.keys()):
                hue = i / len(trajectories)
                plane_colors[plane_id] = plt.cm.hsv(hue)
            
            # Plot each plane's trajectory
            for plane_id, traj in trajectories.items():
                # Get plane data
                plane_data = next((p for p in planes if p['icao24'] == plane_id), None)
                if not plane_data:
                    continue
                
                # Get start and end positions
                start_lat, start_lon = traj[0]['latitude'], traj[0]['longitude']
                end_lat, end_lon = traj[-1]['latitude'], traj[-1]['longitude']
                
                # Draw trajectory with gradient color based on altitude
                lats = [point['latitude'] for point in traj]
                lons = [point['longitude'] for point in traj]
                
                # Use altitude for color
                altitude = traj[0]['altitude']
                base_color = altitude_to_color(altitude)
                
                # Plot the trajectory line with a gradient alpha
                n_points = len(lats)
                for i in range(n_points - 1):
                    alpha = 0.9 - (0.7 * i / n_points)  # Fade out as trajectory extends
                    ax.plot([lons[i], lons[i+1]], [lats[i], lats[i+1]], 
                            color=base_color, alpha=alpha, linewidth=1.5,
                            transform=ccrs.PlateCarree())
                
                # Draw a plane icon at current position with correct heading
                icon_size = 0.02  # Scale factor for the icon
                icon_x, icon_y = create_plane_icon(plane_data['track'])
                ax.fill(start_lon + np.array(icon_x) * icon_size, 
                        start_lat + np.array(icon_y) * icon_size, 
                        color=base_color, edgecolor='black', linewidth=0.5,
                        transform=ccrs.PlateCarree(), zorder=10)
                
                # Add callsign and altitude text near the plane
                if plane_data['callsign']:
                    ax.text(start_lon + icon_size, start_lat + icon_size, 
                            f"{plane_data['callsign'].strip()}\n{int(altitude) if altitude else 'Unknown'} ft", 
                            fontsize=8, fontweight='bold',
                            bbox=dict(facecolor='white', alpha=0.7, edgecolor='none', pad=1),
                            transform=ccrs.PlateCarree(), zorder=11)
            
            # Mark collision events with warning symbols
            for event in collisions:
                # Create a starburst warning symbol
                ax.scatter(event['longitude'], event['latitude'], 
                          color='red', marker='*', s=200, edgecolor='yellow', linewidth=1.5,
                          transform=ccrs.PlateCarree(), zorder=12)
                
                # Add warning text with countdown
                time_to_event = event['time']
                ax.text(event['longitude'], event['latitude'] - 0.02, 
                        f"COLLISION RISK!\nTime: T-{time_to_event}s\nAlt diff: {int(event['vertical_distance'])} ft", 
                        color='red', fontsize=9, fontweight='bold', ha='center',
                        bbox=dict(facecolor='white', alpha=0.9, edgecolor='red', boxstyle='round,pad=0.3'),
                        transform=ccrs.PlateCarree(), zorder=13)
            
            # Add title and grid
            ax.set_title("Real-time Aircraft Collision Avoidance System\n60-Second Trajectory Prediction", 
                         fontsize=14, fontweight='bold', pad=10)
            
            # Add grid lines with labels
            gl = ax.gridlines(crs=ccrs.PlateCarree(), draw_labels=True,
                              linewidth=0.5, color='gray', alpha=0.5, linestyle='--')
            gl.top_labels = False
            gl.right_labels = False
            
            # Update status text
            elapsed = time.time() - start_time
            status_text.set_text(f"Update #{iteration} | Tracking {len(planes)} aircraft | "
                                f"{len(collisions)} potential conflicts detected | "
                                f"Refresh time: {elapsed:.2f}s")
            
            # Update the figure
            fig.canvas.draw_idle()
            plt.pause(max(0.1, 1 - elapsed))  # Aim for 1 second update, but never less than 0.1s

    except KeyboardInterrupt:
        print("Real-time simulation terminated by user.")
        plt.ioff()
        plt.show()
    except Exception as e:
        print(f"Error in real-time simulation: {e}")
        plt.ioff()
        plt.close()

if __name__ == "__main__":
    print("Starting enhanced aircraft collision avoidance visualization...")
    print("Press Ctrl+C to exit.")
    try:
        # Check if cartopy is available, otherwise recommend installation
        import cartopy
        realtime_simulation()
    except ImportError:
        print("\nERROR: This enhanced visualization requires additional packages.")
        print("Please install the required dependencies with:")
        print("pip install matplotlib numpy cartopy requests")