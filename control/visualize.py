import folium
from folium.plugins import MousePosition
from folium.elements import Element
from typing import List, Dict
import geopandas as gpd
import pandas as pd
import json

# Global plane color mapping and palette with better contrasting colors
PLANE_COLORS = {}
COLOR_PALETTE = [
    "#1f77b4", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    "#aec7e8", "#ffbb78", "#98df8a", "#ff9896"
]

def get_plane_color(tail: str) -> str:
    """Assigns a unique color to each plane based on its tail number."""
    if tail not in PLANE_COLORS:
        index = len(PLANE_COLORS) % len(COLOR_PALETTE)
        PLANE_COLORS[tail] = COLOR_PALETTE[index]
    return PLANE_COLORS[tail]

def build_custom_js(m: folium.Map, flights, violations, animation_interval=20):
    """
    Build custom JavaScript for map animation with performance optimizations:
    - Use requestAnimationFrame instead of setTimeout
    - Batch DOM operations
    - Reduce marker creation by using a single marker for each flight
    - Optimize polyline updates
    - Add time controls for playback
    """
    map_name = m.get_name()
    custom_js = f"""
    <script>
    document.addEventListener('DOMContentLoaded', function() {{
        var mapObject = window["{map_name}"];
        
        // Add control panel for animation
        var controlPanel = L.control({{position: 'bottomleft'}});
        controlPanel.onAdd = function(map) {{
            var div = L.DomUtil.create('div', 'control-panel');
            div.style.padding = '10px';
            div.style.background = 'white';
            div.style.borderRadius = '5px';
            div.style.boxShadow = '0 1px 5px rgba(0,0,0,0.4)';
            
            div.innerHTML = `
                <div style="display: flex; align-items: center; margin-bottom: 5px;">
                    <button id="play-pause" style="margin-right: 10px; padding: 5px 10px;">▶️</button>
                    <input type="range" id="speed-slider" min="1" max="100" value="4" style="width: 100px;">
                    <span id="speed-value" style="margin-left: 5px;">4x</span>
                </div>
                <div style="display: flex; align-items: center;">
                    <input type="range" id="time-slider" min="0" max="100" value="0" style="flex-grow: 1; margin-right: 5px;">
                    <span id="current-time-display">00:00</span>
                </div>
            `;
            
            return div;
        }};
        controlPanel.addTo(mapObject);

        function projectPosition(lat, lon, headingDeg, speed, dtSec) {{
            // Earth radius in meters
            var R = 6371000;
            // distance to travel
            var distance = speed * dtSec;  
            // convert everything to radians
            var heading = headingDeg * Math.PI / 180.0;
            var latRad = lat * Math.PI / 180.0;
            var lonRad = lon * Math.PI / 180.0;
            
            // Haversine-like formula
            var newLat = Math.asin(
                Math.sin(latRad) * Math.cos(distance / R) +
                Math.cos(latRad) * Math.sin(distance / R) * Math.cos(heading)
            );
            var newLon = lonRad + Math.atan2(
                Math.sin(heading) * Math.sin(distance / R) * Math.cos(latRad),
                Math.cos(distance / R) - Math.sin(latRad) * Math.sin(newLat)
            );
            
            // convert back to degrees
            return [
                newLat * 180.0 / Math.PI,
                newLon * 180.0 / Math.PI
            ];
        }}


        var flights = {flights};
        var violations = {violations};
        
        // Pre-process data for better performance
        flights.forEach(function(flight) {{
            flight.points.sort(function(a, b) {{
                return a.timestamp - b.timestamp;
            }});
            // Pre-calculate path for efficient access
            flight.path = flight.points.map(p => [p.lat, p.lon]);
            // Index points by timestamp for quick lookup
            flight.pointsByTime = {{}};
            flight.points.forEach(p => {{
                flight.pointsByTime[p.timestamp] = p;
            }});
        }});

        // Find global min/max time across all flights
        var globalMinT = Infinity;
        var globalMaxT = -Infinity;
        flights.forEach(function(flight) {{
            if (flight.points.length > 0) {{
                var firstT = flight.points[0].timestamp;
                var lastT = flight.points[flight.points.length - 1].timestamp;
                if (firstT < globalMinT) globalMinT = firstT;
                if (lastT > globalMaxT) globalMaxT = lastT;
            }}
        }});
        
        if (globalMinT === Infinity || globalMaxT === -Infinity) {{
            console.warn("No valid flight data to animate.");
            return;
        }}
        
        // Set time slider range
        var timeSlider = document.getElementById('time-slider');
        timeSlider.min = 0;
        timeSlider.max = 100;
        timeSlider.value = 0;
        
        // Initialize markers, use icon for better performance
        var flightMarkers = {{}};
        var flightPaths = {{}};
        var flightTrails = {{}};

        // NEW OR MODIFIED CODE:
        // We'll store a separate dashed polyline for predicted paths.
        var flightPredictions = {{}};
        
        // Use a plane icon for better visualization with increased size
        function createPlaneIcon(color, heading) {{
            // Create larger plane icon for better visibility
            var planeSize = 36;
            return L.divIcon({{
                html: `<div style="transform: rotate(${{heading}}deg); width: ${{planeSize}}px; height: ${{planeSize}}px;">
                         <svg viewBox="0 0 24 24" width="${{planeSize}}" height="${{planeSize}}">
                           <path fill="${{color}}" d="M21,16V14L13,9V3.5A1.5,1.5 0 0,0 11.5,2A1.5,1.5 0 0,0 10,3.5V9L2,14V16L10,13.5V19L8,20.5V22L11.5,21L15,22V20.5L13,19V13.5L21,16Z" />
                         </svg>
                       </div>`,
                className: '',
                iconSize: [planeSize, planeSize],
                iconAnchor: [planeSize/2, planeSize/2]
            }});
        }}
        
        // Create layer groups for better performance
        var trailsLayer = L.layerGroup().addTo(mapObject);
        var markersLayer = L.layerGroup().addTo(mapObject);
        var pathsLayer = L.layerGroup().addTo(mapObject);
        
        flights.forEach(function(flight) {{
            var tail = flight.tail;
            if (flight.points.length > 0) {{
                var color = flight.color;
                
                // Create path with the right color
                var path = L.polyline([], {{
                    color: color,
                    weight: 3,
                    opacity: 0.7,
                    smoothFactor: 1
                }});
                flightPaths[tail] = path;
                pathsLayer.addLayer(path);
                
                // Create marker with plane icon
                var startPoint = flight.points[0];
                var marker = L.marker([startPoint.lat, startPoint.lon], {{
                    icon: createPlaneIcon(color, startPoint.heading || 0)
                }});
                marker.bindTooltip(tail, {{permanent: false, direction: 'top', opacity: 0.8}});
                flightMarkers[tail] = marker;
                markersLayer.addLayer(marker);
                
                // Initialize empty trail
                flightTrails[tail] = [];

                // NEW OR MODIFIED CODE:
                // If the flight dictionary has predictedLat/predictedLon, create a dashed polyline for it.
                if (!flightPredictions[tail]) {{
                    var predictedLine = L.polyline([], {{
                        color: color,
                        dashArray: '5,5',  // make it dashed
                        weight: 3,
                        opacity: 0.7,
                        smoothFactor: 1
                    }});
                    flightPredictions[tail] = predictedLine;
                    pathsLayer.addLayer(predictedLine);
                }}
            }}
        }});

        // Create alert box for violations
        var alertBox = document.createElement('div');
        alertBox.style.position = 'absolute';
        alertBox.style.top = '10px';
        alertBox.style.left = '50%';
        alertBox.style.transform = 'translateX(-50%)';
        alertBox.style.zIndex = 9999;
        alertBox.style.padding = '15px';
        alertBox.style.background = 'rgba(255, 0, 0, 0.8)';
        alertBox.style.color = 'white';
        alertBox.style.fontSize = '18px';
        alertBox.style.display = 'none';
        alertBox.style.borderRadius = '5px';
        alertBox.style.boxShadow = '0 2px 10px rgba(0,0,0,0.3)';
        alertBox.style.maxWidth = '80%';
        alertBox.style.textAlign = 'center';
        document.body.appendChild(alertBox);

        function showAlert(msg, rec) {{
            alertBox.innerHTML = `<strong>ALERT</strong><br>${{msg}}<br><b>${{rec}}</b>`;
            alertBox.style.display = 'block';
        }}
        
        function hideAlert() {{
            alertBox.style.display = 'none';
        }}

        // Animation control variables
        var currentTime = globalMinT;
        var animationSpeed = 4;
        var isPlaying = false;
        var lastFrameTime = 0;
        var animationFrame;
        
        // Format time display
        function formatTimeDisplay(timestamp) {{
            var seconds = Math.floor(timestamp - globalMinT);
            var minutes = Math.floor(seconds / 60);
            seconds = seconds % 60;
            return `${{minutes.toString().padStart(2, '0')}}:${{seconds.toString().padStart(2, '0')}}`;
        }}

        // Update time slider without triggering change event
        function updateTimeSliderSilently(time) {{
            var percentage = (time - globalMinT) / (globalMaxT - globalMinT) * 100;
            timeSlider.value = percentage;
            document.getElementById('current-time-display').textContent = formatTimeDisplay(time);
        }}

        // Animation step with requestAnimationFrame for smoother performance
        function animationStep(timestamp) {{
            if (!isPlaying) return;
            
            // Calculate time difference for consistent animation speed
            if (!lastFrameTime) lastFrameTime = timestamp;
            var elapsed = timestamp - lastFrameTime;
            
            // Only update if enough time has passed (based on animation speed)
            if (elapsed > (1000 / animationSpeed)) {{
                lastFrameTime = timestamp;
                
                // If reached the end, stop but keep final positions
                if (currentTime >= globalMaxT) {{
                    isPlaying = false;
                    document.getElementById('play-pause').innerHTML = '▶️';
                    // Don't hide alert if there's one at the end
                    // Don't reset positions - keep planes at their final locations
                    return;
                }}
                
                // Step time forward by a amount appropriate for 4x speed
                currentTime += 0.4;
                
                // Update positions
                updatePositions(currentTime);
                
                // Update time display and slider
                updateTimeSliderSilently(currentTime);
            }}
            
            animationFrame = requestAnimationFrame(animationStep);
        }}

        // Update all flight positions for a given time
        function updatePositions(time) {{
            // Batch DOM updates for performance
            flights.forEach(function(flight) {{
                var tail = flight.tail;
                if (!flight.points.length) return;
                
                // Find the last point before or at current time
                var lastPointIndex = flight.points.findIndex(p => p.timestamp > time) - 1;
                if (lastPointIndex < 0 && flight.points[0].timestamp <= time) lastPointIndex = 0;
                if (lastPointIndex >= 0) {{
                    var point = flight.points[lastPointIndex];
                    var nextPoint = flight.points[lastPointIndex + 1];
                    
                    var pos, heading, speed;
                    if (nextPoint && nextPoint.timestamp <= time) {{
                        // Exact point match
                        pos = [point.lat, point.lon];
                        heading = point.heading || 0;
                        speed = point.speed || 0;
                    }} else if (nextPoint) {{
                        // Interpolate between points for smoother motion
                        var ratio = (time - point.timestamp) / (nextPoint.timestamp - point.timestamp);
                        ratio = Math.min(1, Math.max(0, ratio)); // Clamp between 0 and 1
                        
                        pos = [
                            point.lat + (nextPoint.lat - point.lat) * ratio,
                            point.lon + (nextPoint.lon - point.lon) * ratio
                        ];
                        
                        // Interpolate heading
                        var headingDiff = (nextPoint.heading || 0) - (point.heading || 0);
                        // Handle angle wrapping
                        if (headingDiff > 180) headingDiff -= 360;
                        if (headingDiff < -180) headingDiff += 360;
                        heading = (point.heading || 0) + headingDiff * ratio;
                        
                        speedDiff = (nextPoint.speed || 0) - (point.speed || 0);
                        speed = (point.speed || 0) + speedDiff * ratio;
                    }} else {{
                        // Just use the last point
                        pos = [point.lat, point.lon];
                        heading = point.heading || 0;
                    }}
                    
                    // Update marker position and rotation
                    var marker = flightMarkers[tail];
                    marker.setLatLng(pos);
                    
                    // Update plane icon rotation
                    var icon = createPlaneIcon(flight.color, heading);
                    marker.setIcon(icon);
                    
                    // Add to trail (only every few points for performance)
                    if (flightTrails[tail].length === 0 || 
                        L.latLng(flightTrails[tail][flightTrails[tail].length-1]).distanceTo(L.latLng(pos)) > 50) {{
                        flightTrails[tail].push(pos);
                        
                        // Update path - use the efficient setLatLngs method
                        flightPaths[tail].setLatLngs(flightTrails[tail]);
                    }}

                    // NEW OR MODIFIED CODE:
                    // If there is a prediction line for this flight, update its lat/lng 
                    // to go from the current position to the predicted position.
                    if (flightPredictions[tail]) {{
                        var dtAhead = 10.0;
                        var predictedPos = projectPosition(pos[0], pos[1], heading, speed, dtAhead);
                        flightPredictions[tail].setLatLngs([pos, predictedPos]);
                    }}
                }}
            }});
            
            // Check for violations at this time
            checkViolations(time);
        }}
        
        // Store the current violation to keep it visible longer
        var currentViolation = null;
        var violationStartTime = 0;
        var violationDisplayDuration = 10; // Show violations for 10 seconds
        
        // Check for violations near the current time
        function checkViolations(time) {{
            // Find violations within a small time window
            var found = false;
            Object.keys(violations).forEach(function(vtime) {{
                var t = parseFloat(vtime);
                if (Math.abs(t - time) < 1) {{ // Within 1 second tolerance
                    var v = violations[vtime];
                    showAlert(v.message, v.advisory);
                    currentViolation = v;
                    violationStartTime = time;
                    found = true;
                }}
            }});
            
            // Keep showing existing violation for the duration
            if (!found && currentViolation) {{
                if (time - violationStartTime < violationDisplayDuration) {{
                    // Keep showing the current violation
                    showAlert(currentViolation.message, currentViolation.advisory);
                    found = true;
                }} else {{
                    // Clear the violation after duration
                    currentViolation = null;
                }}
            }}
            
            if (!found) {{
                hideAlert();
            }}
        }}
        
        // Control panel event handlers
        document.getElementById('play-pause').addEventListener('click', function() {{
            isPlaying = !isPlaying;
            this.innerHTML = isPlaying ? '⏸️' : '▶️';
            
            if (isPlaying) {{
                // If at the end, start over
                if (currentTime >= globalMaxT) {{
                    currentTime = globalMinT;
                    // Reset trails
                    flights.forEach(function(flight) {{
                        var tail = flight.tail;
                        if (flightTrails[tail]) {{
                            flightTrails[tail] = [];
                            flightPaths[tail].setLatLngs([]);
                        }}
                    }});
                }}
                
                lastFrameTime = 0;
                animationFrame = requestAnimationFrame(animationStep);
            }} else {{
                cancelAnimationFrame(animationFrame);
            }}
        }});
        
        // Speed slider control
        document.getElementById('speed-slider').addEventListener('input', function() {{
            animationSpeed = parseInt(this.value);
            document.getElementById('speed-value').textContent = animationSpeed + 'x';
        }});
        
        // Time slider control
        document.getElementById('time-slider').addEventListener('input', function() {{
            // Pause animation while scrubbing
            var wasPlaying = isPlaying;
            if (isPlaying) {{
                isPlaying = false;
                cancelAnimationFrame(animationFrame);
            }}
            
            // Calculate time based on slider position
            var percentage = parseInt(this.value) / 100;
            currentTime = globalMinT + (globalMaxT - globalMinT) * percentage;
            
            // Only reset trails if going back in time
            var currentPercentage = (currentTime - globalMinT) / (globalMaxT - globalMinT) * 100;
            if (parseInt(this.value) < currentPercentage) {{
                flights.forEach(function(flight) {{
                    var tail = flight.tail;
                    if (flightTrails[tail]) {{
                        flightTrails[tail] = [];
                        flightPaths[tail].setLatLngs([]);
                    }}
                }});
            }}
            
            // Update display
            document.getElementById('current-time-display').textContent = formatTimeDisplay(currentTime);
            
            // Rebuild trails up to current time
            var stepTime = globalMinT;
            var timeStep = Math.max(1, (currentTime - globalMinT) / 100); // Divide into 100 steps max
            
            while (stepTime < currentTime) {{
                updatePositions(stepTime);
                stepTime += timeStep;
            }}
            
            // Final update at exactly the target time
            updatePositions(currentTime);
            
            // Resume if it was playing before
            if (wasPlaying) {{
                isPlaying = true;
                lastFrameTime = 0;
                animationFrame = requestAnimationFrame(animationStep);
            }}
        }});
        
        // Initialize positions
        updatePositions(globalMinT);
        
        // Auto-start playback
        document.getElementById('play-pause').click();
    }});
    </script>
    
    <style>
    /* Custom CSS for better visualization */
    .leaflet-popup-content-wrapper {{
        border-radius: 5px;
    }}
    .leaflet-tooltip {{
        background-color: rgba(0, 0, 0, 0.7);
        color: white;
        border: none;
        padding: 5px 10px;
        font-weight: bold;
        border-radius: 3px;
    }}
    </style>
    """
    return Element(custom_js)

def build_animated_map(center_lat: float, center_lon: float,
                       static_features: List[gpd.GeoDataFrame],
                       flight_geojson: Dict,
                       plane_histories: Dict[str, pd.DataFrame],
                       flagged_events: List[Dict],
                       animation_speed: float = 1.0) -> folium.Map:
    """
    Constructs an interactive Folium map with improved performance
    and visual display of flight paths and runway incursions.
    """

    # Create the base Folium map
    m = folium.Map(
        location=[center_lat, center_lon], 
        zoom_start=14, 
        tiles="CartoDB Positron",
        control_scale=True
    )

    # Add mouse-position plugin
    MousePosition(
        position="topright",
        separator=" | ",
        prefix="Lat/Long:",
        lat_formatter="function(num) {return L.Util.formatNum(num, 5);}",
        lng_formatter="function(num) {return L.Util.formatNum(num, 5);}"
    ).add_to(m)

    # Add static features: runways & taxiways
    runways, taxiways = static_features
    if not runways.empty:
        folium.GeoJson(
            runways.__geo_interface__,
            name="Runways",
            style_function=lambda f: {
                'color': '#ff7700', 
                'weight': 3, 
                'fillOpacity': 0.3,
                'fillColor': '#ffaa00'
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["ref", "name"], 
                aliases=["Runway", "Name"], 
                localize=True,
                sticky=True
            )
        ).add_to(m)
    
    if not taxiways.empty:
        folium.GeoJson(
            taxiways.__geo_interface__,
            name="Taxiways",
            style_function=lambda f: {
                'color': '#95c5e8', 
                'weight': 2, 
                'fillOpacity': 0.2,
                'fillColor': '#c7e1f6'
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["ref", "name"], 
                aliases=["Taxiway", "Name"], 
                localize=True,
                sticky=True
            )
        ).add_to(m)

    # Prepare flight data for animation
    flight_data_js = []
    for tail, df in plane_histories.items():
        df_sorted = df.sort_values("Timestamp")
        points_list = []
        
        for _, row in df_sorted.iterrows():
            lat = row["lat"]
            lon = row["lon"]
            speed = row.get("Speed", 0)
            bearing = row.get("Direction", 0)
            timestamp = row["Timestamp"]
            # from geopy.distance import distance
            # distance_ahead = speed * 5.0
            # destination = distance(meters=distance_ahead).destination((lat, lon), bearing)
            # pred_lat, pred_lon = destination.latitude, destination.longitude
            points_list.append({
                "lat": lat,
                "lon": lon,
                "speed": speed,
                "heading": bearing,
                "timestamp": timestamp
            })
        
        flight_dict = {
            "tail": tail,
            "points": points_list,
            "color": get_plane_color(tail),
        }
        
        flight_data_js.append(flight_dict)

    # Create violations dictionary
    violations_by_time = {}
    for ev in flagged_events:
        ts = ev["timestamp"]
        violations_by_time[ts] = {
            "message": ev["message"],
            "tail": ev["tail"],
            "advisory": ev["advisory"],
            "prediction": ev["prediction"]
        }

    # Convert to JSON for embedding in JS
    flight_data_json = json.dumps(flight_data_js)
    violations_json = json.dumps(violations_by_time)

    # Calculate animation interval based on speed
    animation_interval = int(50 / animation_speed)  # 50ms base / speed modifier

    # Add the custom JavaScript to the map
    custom_element = build_custom_js(
        m, 
        flights=flight_data_json, 
        violations=violations_json,
        animation_interval=animation_interval
    )
    m.get_root().html.add_child(custom_element)

    # Add layer control
    folium.LayerControl().add_to(m)
    
    return m
