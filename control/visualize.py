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

import folium
from folium.plugins import MousePosition
from folium.elements import Element
# ----------------------------------------------------------------
# 1) Construct a custom <script> block to animate the data
# ----------------------------------------------------------------
# We'll store flight lines in Leaflet layers and reveal them step by step.
# For each step:
#   1) We pick the next point for each flight if the timestamp <= current time
#   2) If there's a violation at the current time, show a big alert overlay
#   3) We increment current time and repeat
# This is a minimal example – you can refine how you do the stepping logic.

def build_custom_js(m: folium.Map, flights, violations):
    map_name = m.get_name()
    custom_js = """
    :param m: The Folium map object
    :param flights_data: A Python list of flight objects, each like:
        [
          {
            "tail": "SWA2504",
            "points": [
               {"lat": 41.786, "lon": -87.754, "timestamp": 1740494856.48, ...},
               ...
            ]
          },
          {
            "tail": "LXJ560",
            "points": [...],
          }
        ]
      (Make sure each sub-list is sorted, or we can sort in JS)
    :param violations_data: A dictionary keyed by timestamp (float or int),
       e.g. {
         1740494856.48: {"message": "some incursion", "advisory": "STOP NOW"},
         ...
       }
      or you can store them as floats or strings. Just be consistent in the JS.
    """

    # We'll embed a single custom script that:
    # 1) Finds the global minT & maxT across all flights
    # 2) Steps from minT to maxT
    # 3) For each flight, if currentTime >= that flight's earliest, we place/update the marker
    # 4) We also place a small circle marker each step, like a "pen" leaving dots on the map
    # 5) Check if there's a violation at the current time (global) and show/hide an alert

    map_name = m.get_name()
    custom_js = f"""
    <script>
    document.addEventListener('DOMContentLoaded', function() {{
        var mapObject = window["{map_name}"];

        var flights = {flights};
        var violations = {violations};

        // 1) Sort each flight's points by ascending timestamp (in case not sorted)
        flights.forEach(function(flight) {{
            flight.points.sort(function(a, b) {{
                return a.timestamp - b.timestamp;
            }});
        }});

        // 2) Find global minT & maxT across all flights
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

        // If no data at all, do nothing
        if (globalMinT === Infinity || globalMaxT === -Infinity) {{
            console.warn("No valid flight data to animate.");
            return;
        }}

        // 3) For each flight, create a polyline & marker object
        // We'll store them in a dictionary keyed by flight tail
        var flightMarkers = {{}};
        var flightPolylines = {{}};
        var flightMinTime = {{}};
        flights.forEach(function(flight) {{
            var tail = flight.tail;
            if (flight.points.length > 0) {{
                // polyline
                var poly = L.polyline([], {{color: 'red', weight: 3}}).addTo(mapObject);
                flightPolylines[tail] = poly;

                // marker at first point
                var startLat = flight.points[0].lat;
                var startLon = flight.points[0].lon;
                var marker = L.marker([startLat, startLon]).addTo(mapObject);
                flightMarkers[tail] = marker;

                // store the earliest time
                flightMinTime[tail] = flight.points[0].timestamp;
            }}
        }});

        // 4) Create a single alertBox for violations
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
        document.body.appendChild(alertBox);

        function showAlert(msg, rec) {{
            alertBox.innerHTML = msg + "<br/><b>" + rec + "</b>";
            alertBox.style.display = 'block';
        }}
        function hideAlert() {{
            alertBox.style.display = 'none';
        }}

        // 5) Step from globalMinT to globalMaxT in 1-second increments (or whatever)
        var currentTime = globalMinT;

        function stepSimulation() {{
            if (currentTime > globalMaxT) {{
                // done
                hideAlert();
                return;
            }}

            // For each flight, if currentTime >= flightMinTime, we pick the last known point up to currentTime
            flights.forEach(function(flight) {{
                var tail = flight.tail;
                if (!flight.points.length) return; // skip empty

                var minT = flightMinTime[tail];
                if (currentTime < minT) return; // plane hasn't started

                // find the last known point up to currentTime
                var relevant = flight.points.filter(p => p.timestamp <= currentTime);
                if (relevant.length > 0) {{
                    var pt = relevant[relevant.length - 1];
                    // update marker
                    flightMarkers[tail].setLatLng([pt.lat, pt.lon]);

                    // "literal marker": place small circle
                    L.circleMarker([pt.lat, pt.lon], {{
                        radius: 3,
                        color: 'blue',
                        fillColor: 'blue',
                        fillOpacity: 0.7
                    }}).addTo(mapObject);

                    // extend the polyline
                    var poly = flightPolylines[tail];
                    var latlngs = poly.getLatLngs();
                    latlngs.push([pt.lat, pt.lon]);
                    poly.setLatLngs(latlngs);
                }}
            }});

            // Check if there's a violation at this time
            // Note: if your violations keys are floats, you might need parseFloat or rounding
            var vkey = String(currentTime); // or parseFloat
            if (violations[vkey]) {{
                var v = violations[vkey];
                showAlert(v.message, v.advisory);
            }} else {{
                hideAlert();
            }}

            var stepSize = 1; // flight-seconds
            currentTime += stepSize;
            console.log(currentTime)
            setTimeout(stepSimulation, 1000);
        }}

        stepSimulation();
    }});
    </script>
    """
    return Element(custom_js)

def build_animated_map(center_lat: float, center_lon: float,
                       static_features: List[gpd.GeoDataFrame],
                       flight_geojson: Dict,
                       plane_histories: Dict[str, pd.DataFrame],
                       flagged_events: List[Dict],
                       animation_speed: float = 1.0) -> folium.Map:
    """
    Constructs an interactive Folium map that:
      1) Displays static features (runways/taxiways),
      2) Animates flight paths step by step, applying a speed coefficient,
      3) Shows a persistent on-map alert when a compliance violation occurs,
         with the recommended command from your recommendation engine.
    """

    # ----------------------------------------------------------------
    # 1) Create the base Folium map
    # ----------------------------------------------------------------
    m = folium.Map(location=[center_lat, center_lon], zoom_start=14, tiles="cartodbpositron")

    # Add mouse-position plugin
    MousePosition(
        position="topright",
        separator=" | ",
        prefix="Lat/Long:",
        lat_formatter="function(num) {return L.Util.formatNum(num, 5);}",
        lng_formatter="function(num) {return L.Util.formatNum(num, 5);}"
    ).add_to(m)

    # ----------------------------------------------------------------
    # 2) Add static features: runways & taxiways
    # ----------------------------------------------------------------
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

    # ----------------------------------------------------------------
    # 3) Prepare data for animation in JavaScript
    # ----------------------------------------------------------------
    # We'll create arrays of data for each flight's positions, sorted by time.
    # Also store violation info keyed by timestamp if desired.
    # For real usage, you may prefer to unify all flight data into a single array
    # sorted by time. This is just a simplified example.
    flight_data_js = []
    for tail, df in plane_histories.items():
        # Sort by ascending timestamp
        df_sorted = df.sort_values("Timestamp")
        # We'll build a simple list of {lat, lon, speed, time, tail} per row
        points_list = []
        for _, row in df_sorted.iterrows():
            points_list.append({
                "lat": row["lat"],
                "lon": row["lon"],
                "speed": row.get("Speed", 0),
                "heading": row.get("Direction", 0),
                "timestamp": row["Timestamp"]
            })
        flight_data_js.append({
            "tail": tail,
            "points": points_list,
            "color": get_plane_color(tail)
        })

    # Also create a dictionary for flagged events keyed by the exact timestamp:
    # If multiple events share the same timestamp, we can unify them as well.
    # e.g. flagged_events = [{ "timestamp": 1740494872, "message": "...", "advisory": "...", etc. }, ...]
    # We'll store them in a dictionary for quick lookup:
    violations_by_time = {}
    for ev in flagged_events:
        ts = ev["timestamp"]
        violations_by_time[ts] = {
            "message": ev["message"],
            "tail": ev["tail"],
            "advisory": ev["advisory"],  # or "recommendation"
            "prediction": ev["prediction"]
        }

    # We'll embed these data structures in the HTML/JS as JSON strings
    import json
    flight_data_json = json.dumps(flight_data_js)
    violations_json = json.dumps(violations_by_time)

    # Convert animation_speed to a "millisecond" step in JS
    # e.g. if animation_speed=2.0, we might want to move 2 times faster.
    # We'll define a base interval (like 500ms) and scale it:
    base_interval_ms = 500  # base = half a second
    animation_interval = int(base_interval_ms / animation_speed)

    custom_js = build_custom_js(m, flights=flight_data_json, violations=violations_json)
    custom_element = custom_js

    # Add the custom element to the map's HTML
    m.get_root().html.add_child(custom_element)

    folium.LayerControl().add_to(m)
    return m
