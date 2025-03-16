from shapely.geometry import LineString
from typing import List, Dict
import geopandas as gpd
import pandas as pd
import logging

class Flights:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)
        handler = logging.FileHandler("debug-flights.log")
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.FATAL)

        FLAGGED_INCURSIONS = {}
        self.FLAGGED_INCURSIONS = FLAGGED_INCURSIONS

        self.interval = 30
    
    def _getFlaggedIncursions(self):
        return self.FLAGGED_INCURSIONS

    def map_flight_identifier(self, flight_name: str) -> str:
        """
        Maps an ATC flight name to its ADS-B tail identifier.
        Adjust mapping as needed.
        """
        logger = self.logger
        logger.debug(f"map_flight_identifier called with flight_name={flight_name}")
        mapping = {
            "Southwest 2504": "SWA2504",
            "FlexJet 560":    "LXJ560"
        }
        for key, ident in mapping.items():
            if key in flight_name:
                logger.debug(f"match found: {key} -> {ident}")
                return ident
        logger.debug(f"no mapping found, returning original flight_name={flight_name}")
        return flight_name

    def get_feature_geometry(self, ref: str, static_features: List[gpd.GeoDataFrame]):
        """
        Given a feature reference (e.g. runway, taxiway name),
        returns the corresponding geometry from the static feature layers.
        """
        logger = self.logger
        logger.debug(f"get_feature_geometry called with ref={ref}")
        for idx_group, group in enumerate(static_features):
            for _, row in group.iterrows():
                candidate_ref = str(row.get("ref", "")).strip()
                if candidate_ref == ref.strip():
                    logger.debug(f"match found in group {idx_group}: {candidate_ref}")
                    return row.geometry
        logger.debug("no matching feature geometry found.")
        return None
    
    def recommend_action(self, violation_msg: str) -> Dict[str, str]:
        """
        Returns a concise, actionable pilot command (e.g. "STOP NOW") plus
        a reasonably expected outcome in the system's absence based on  violation message.
        """
        # Basic rule-based approach: parse or match keywords in violation_msg
        # and produce a succinct recommended action + predicted outcome.
        if "HOLD" in violation_msg:
            return {
                "advisory": "STOP NOW",
                "prediction": "Likely collision or incursion on restricted path."
            }
        elif "crossing runway" in violation_msg or "incursion" in violation_msg:
            return {
                "advisory": "EXIT RUNWAY",
                "prediction": "Severe risk of collision with landing aircraft."
            }
        elif "too fast" in violation_msg:
            return {
                "advisory": "REDUCE SPEED",
                "prediction": "Runway overrun or ground collision."
            }
        else:
            # Default fallback
            return {
                "advisory": "MAINTAIN POSITION",
                "prediction": "Potential unknown hazard."
            }
        
    def project_position(self, lat: float, lon: float, heading_deg: float, speed: float, dt_sec: float):
        """
        Predicts a future position given current lat/lon, heading, speed, and time delta (seconds).
        """
        R = 6371000  # Earth radius in meters
        distance_ahead = speed * dt_sec
        import math
        heading_rad = math.radians(heading_deg)
        lat_rad = math.radians(lat)
        lon_rad = math.radians(lon)

        new_lat_rad = math.asin(
            math.sin(lat_rad) * math.cos(distance_ahead / R) +
            math.cos(lat_rad) * math.sin(distance_ahead / R) * math.cos(heading_rad)
        )

        new_lon_rad = lon_rad + math.atan2(
            math.sin(heading_rad) * math.sin(distance_ahead / R) * math.cos(lat_rad),
            math.cos(distance_ahead / R) - math.sin(lat_rad) * math.sin(new_lat_rad)
        )

        new_lat = math.degrees(new_lat_rad)
        new_lon = math.degrees(new_lon_rad)

        return new_lat, new_lon

    def evaluate_compliance(self,
                            plane: str,
                            prev_lat: float,
                            prev_lon: float,
                            current_lat: float,
                            current_lon: float,
                            speed: float,
                            bearing: float,
                            static_features: List[gpd.GeoDataFrame],
                            current_time: float,
                            instructions: List[Dict]) -> Dict[str, str]:
        """
        Checks:
            If there's a HOLD_SHORT / HOLD_POSITION in effect, ensure no crossing occurs
            of the instructed feature unless CLEAR_TO_CROSS is found.

        We now form a line from the real flight path (current → predicted). If that line
        intersects the relevant geometry (and no clearance was given), we flag it.
        """
        logger = self.logger
        logger.debug(f"evaluate_compliance called for plane={plane} at time={current_time}")

        # Build the real flight line from the last fix to the current fix
        flight_line = LineString([(current_lon, current_lat), (prev_lon, prev_lat)])

        # 1) Check if plane has a HOLD_POSITION or HOLD_SHORT instruction in effect
        relevant_instr = [
            i for i in instructions
            if self.map_flight_identifier(i["plane"]) == plane and i["time"] <= current_time
        ]
        relevant_instr.sort(key=lambda x: x["time"])
        logger.debug(f"relevant_instr found = {len(relevant_instr)} up to current_time={current_time}")
        if relevant_instr:
            last_instr = relevant_instr[-1]
            logger.debug(f"last_instr for plane={plane} is {last_instr}")
            hold_commands = {"HOLD_POSITION", "HOLD_SHORT"}
            if last_instr["instr"] in hold_commands:
                hold_ref = last_instr["reference"].strip()
                logger.debug(f"Detected hold instruction {last_instr['instr']} for reference={hold_ref}")
                cleared = [
                    i for i in instructions
                    if self.map_flight_identifier(i["plane"]) == plane
                    and i["instr"] == "CLEAR_TO_CROSS"
                    and i["time"] > last_instr["time"]
                    and i["time"] <= current_time
                    and i["reference"].strip() == hold_ref
                ]
                logger.debug(
                    f"CLEARED_TO_CROSS found={len(cleared)} for {hold_ref} after hold time={last_instr['time']}"
                )
                if not cleared and hold_ref:
                    feature_geom = self.get_feature_geometry(hold_ref, static_features)
                    feature_geom = feature_geom.buffer(40)
                    if feature_geom is not None and flight_line.intersects(feature_geom):
                        logger.debug(f"HOLD violation detected for plane={plane} on {hold_ref}")
                        violation_msg = (
                            f"Non-compliant: {plane} violated {last_instr['instr']} at {hold_ref} "
                            f"after it was issued (no CLEAR_TO_CROSS)."
                        )
                        recommendation = self.recommend_action(violation_msg)
                        return {
                            "message": violation_msg,
                            "ref": hold_ref,
                            "timestamp": current_time,
                            "lat": current_lat,
                            "lon": current_lon,
                            "speed": speed,
                            "heading": bearing,
                            "interval": self.interval,
                            "prediction": recommendation["prediction"],
                            "advisory": recommendation["advisory"]
                        }

        logger.debug("No compliance violations detected.")
        return {"message": "In compliance", "ref": ""}

    def log_flagged_incursions(self,
                               plane_histories: Dict[str, pd.DataFrame],
                               instructions: List[Dict],
                               static_features: List[gpd.GeoDataFrame],
                               interval: int = 5) -> List[Dict]:
        """
        Iterates through flight history (for all planes).
        For each record, we now consider the line from the current record
        to the predicted record. If the line intersects a geometry that should 
        not be crossed, logs a violation.
        """
        logger = self.logger
        self.interval = interval
        logger.debug("log_flagged_incursions called.")

        events = []
        for tail, df in plane_histories.items():
            logger.debug(f"Processing plane={tail} with {len(df)} records.")
            
            prev_row = None
            pred_lat, pred_lon = None, None

            for _, row in df.iterrows():
                if prev_row is None:
                    # For the first row, initialize predicted positions with actual values
                    pred_lat, pred_lon = row["lat"], row["lon"]
                    prev_row = row
                    continue

                # Compute predicted positions based on previous prediction
                time_ahead_intervals = [5, 10, 15, 20, 25, 30]  # Seconds into the future
                current_lat, current_lon = row["lat"], row["lon"]
                
                for dt_sec in time_ahead_intervals:
                    pred_lat, pred_lon = self.project_position(
                        lat=current_lat,
                        lon=current_lon,
                        heading_deg=row["Direction"],
                        speed=row["Speed"],
                        dt_sec=dt_sec
                    )

                # Evaluate compliance using predicted positions
                result = self.evaluate_compliance(
                    plane=tail,
                    prev_lat=current_lat,
                    prev_lon=current_lon,
                    current_lat=pred_lat,
                    current_lon=pred_lon,
                    speed=row["Speed"],
                    bearing=row["Direction"],
                    static_features=static_features,
                    current_time=row["Timestamp"] + (dt_sec*0.8),
                    instructions=instructions
                )

                if "Non-compliant" in result["message"]:
                    key = (tail, result["ref"])
                    if key not in self.FLAGGED_INCURSIONS:
                        self.FLAGGED_INCURSIONS[key] = {
                            "tail": tail,
                            "timestamp": result["timestamp"],
                            "lat": result["lat"],
                            "lon": result["lon"],
                            "message": result["message"],
                            "ref": result["ref"],
                            "speed": result["speed"],
                            "heading": result["heading"],
                            "interval": result["interval"],
                            "prediction": result["prediction"],
                            "advisory": result["advisory"]
                        }
                        print(f"[EARLY WARNING] {tail}: {result['message']} at t+{dt_sec}s")
                        events.append(self.FLAGGED_INCURSIONS[key])

                prev_row = row  # Update for next iteration
        logger.debug("log_flagged_incursions completed.")
        return events