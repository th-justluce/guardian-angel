# README
## Overview
(Will populate from slides at some point)

## Project Structure
```bash
.
├── README.md
├── collision_avoidance.py
├── compliant_state
│   ├── SWA2504.mp3
│   ├── __init__.py
│   ├── cache
│   │   ├── SWA2504_openai_response.json
│   │   └── SWA2504_transcription.json
│   ├── compliant_state_prompt.txt
│   └── produce_state.py
├── control
│   ├── __init__.py
│   ├── adsb
│   │   ├── __init__.py
│   │   ├── adsb_manager.py
│   │   └── csvs
│   │       ├── LXJ560_39427139.csv
│   │       └── WN2504_39423039.csv
│   ├── alert-stop.wav
│   ├── controller.py
│   ├── features.py
│   ├── flights.py
│   ├── kmdw_interactive_flight_map.html
│   └── visualize.py
├── presentation
│   ├── plane_missile_collision.gif
│   └── plot.py
└── requirements.txt
```

### Feature Rundown
collision_avoidance.py takes in ADS-B data and handles the collision avoidance calculations for all aircraft nearby.

Within the presentation folder, we simply have a lovely missle animation to highlight how little time a fighter pilot may have to react.
We cut it from the presentation for time.

Within the control folder:
- adsb/adsb_manager.py handles reading CSVs containg ADS-B data, which we use to backtest against historic incidents
- controller.py manages aircraft movement on the ground and ensures compliance with ATC instructions.
- features.py assists in airport map generation (to ensure we know where we are relative to taxiways, runways, etc.)
- flights.py handles the flight paths and calculates/predicts their future positions
- visualize.py generates a visual of any interaction/incident/event

Within the compliant_state folder,
- We are taking in ATC audio, running it through a speech -> text transformer model, turning into actionable intent via llama3-8b and outputting it for compliance validation.
- produce_state.py runs on the Jetson to execute the above