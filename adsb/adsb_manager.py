import os
import glob
import logging
import pandas as pd
from math import radians, sin, cos, sqrt, atan2

# Set up basic logging configuration.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def haversine(lat1, lon1, lat2, lon2):
    """
    Calculate the great-circle distance between two points on Earth.
    Returns distance in miles.
    """
    R = 3958.8  # Earth radius in miles
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2)**2 + cos(lat1) * cos(lat2) * sin(dlon / 2)**2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c

class AircraftTracker:
    def __init__(self, folder_path="CSVs"):
        """
        Loads all CSV files from the specified folder into memory.
        Each CSV is assumed to have the following columns:
          - Timestamp: Unix timestamp (integer)
          - UTC: UTC time (string)
          - Callsign: tail number / identifier of the aircraft
          - Position: a string in the format "lat,lon"
          - Altitude, Speed, Direction: other flight data
        """
        self.aircraft_data = {}  # Dictionary mapping tail number to its DataFrame
        file_list = glob.glob(os.path.join(folder_path, "*.csv"))
        if not file_list:
            logging.warning(f"No CSV files found in folder: {folder_path}")
        
        for file in file_list:
            try:
                df = pd.read_csv(file)
                # Convert Timestamp column to numeric (Unix timestamp)
                df['Timestamp'] = pd.to_numeric(df['Timestamp'], errors='coerce')
                df = df.dropna(subset=['Timestamp'])
                # Extract latitude and longitude from the "Position" column.
                df[['lat', 'lon']] = df['Position'].str.split(',', expand=True).astype(float)
                # Use the Callsign column as our tail number identifier.
                df['tail_number'] = df['Callsign']
                # Sort the DataFrame by Timestamp to enable efficient querying.
                df = df.sort_values('Timestamp')
                # Assume each CSV file is for one aircraft; use the first row's tail number.
                tail = df.iloc[0]['tail_number']
                self.aircraft_data[tail] = df
                logging.info(f"Loaded data for tail '{tail}' from file '{file}' with {len(df)} records.")
            except Exception as e:
                logging.error(f"Failed to load file '{file}': {e}")

    def get_nearby_aircraft(self, our_tail, query_timestamp):
        """
        Returns a list of dictionaries for aircraft within 5 miles of our aircraft 
        (identified by our_tail) at the given Unix timestamp.

        Parameters:
          our_tail (str): Tail number (Callsign) of our aircraft.
          query_timestamp (int): Unix timestamp at which to query positions.

        Returns:
          List[dict]: Each dictionary contains:
            - tail_number: the aircraft's tail number
            - lat: latitude at the query time
            - lon: longitude at the query time
            - distance_miles: distance from our aircraft (in miles)
            - timestamp: the aircraft's timestamp used for the query
        """
        # Retrieve our aircraft's data.
        our_df = self.aircraft_data.get(our_tail)
        if our_df is None:
            logging.error(f"Our aircraft data for tail '{our_tail}' was not found.")
            return []

        # Get the most recent record at or before the query_timestamp.
        our_rows = our_df[our_df['Timestamp'] <= query_timestamp]
        if our_rows.empty:
            logging.warning(f"No data for our aircraft '{our_tail}' at or before timestamp {query_timestamp}.")
            return []
        our_row = our_rows.iloc[-1]
        our_position = (our_row['lat'], our_row['lon'])
        logging.info(f"Our aircraft '{our_tail}' position at timestamp {query_timestamp}: {our_position}")

        nearby = []
        # Iterate through all aircraft data.
        for tail, df in self.aircraft_data.items():
            if tail == our_tail:
                continue  # Skip our own aircraft

            rows = df[df['Timestamp'] <= query_timestamp]
            if rows.empty:
                logging.debug(f"No data for aircraft '{tail}' at or before timestamp {query_timestamp}.")
                continue

            row = rows.iloc[-1]
            distance = haversine(our_position[0], our_position[1], row['lat'], row['lon'])
            print(distance)
            if distance <= 5:
                logging.info(f"Aircraft '{tail}' is {distance:.2f} miles away.")
                nearby.append({
                    'tail_number': tail,
                    'lat': row['lat'],
                    'lon': row['lon'],
                    'distance_miles': distance,
                    'timestamp': row['Timestamp']
                })

        return nearby

# Example usage:
# if __name__ == "__main__":
#     # Instantiate the tracker, which loads all CSVs from the "CSVs" folder.
#     tracker = AircraftTracker(folder_path="csvs")
    
#     # Define our aircraft's tail number and a query Unix timestamp.
#     our_tail_number = "SWA2504"  # Use the Callsign from the CSV example.
#     query_timestamp = 1740495452  # Example Unix timestamp from the CSV data.
    
#     nearby_aircraft = tracker.get_nearby_aircraft(our_tail_number, query_timestamp)
#     print("Aircraft within 5 miles:", nearby_aircraft)
