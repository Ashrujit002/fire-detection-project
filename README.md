# NASA FIRMS Thermal Source Intelligence — Basic Prototype

This prototype implements:

NASA FIRMS → Flask → Leaflet/OpenStreetMap → hotspot details → transparent risk score.

It is intentionally simple. The "risk" and "classification" are heuristic rules, NOT a trained AI model.

## 1. Install

Python 3.10+ recommended.

Windows:


## 2. Get a free NASA FIRMS MAP_KEY

Open:

https://firms.modaps.eosdis.nasa.gov/api/map_key/

Enter your email and NASA will send your MAP_KEY.



## Open:

http://127.0.0.1:6969

## What this version does

- Fetches real VIIRS Suomi-NPP NRT hotspot data from NASA FIRMS.
- Displays hotspots on a real OpenStreetMap/Leaflet map.
- Shows FRP, confidence, date, time, satellite and brightness information.
- Calculates a transparent prototype risk score.
- Counts high/medium/low risk hotspots.
- for retrain model ->   python train_model.py

## What it does NOT do yet

- It does not use OSM POIs to identify factories/farms.
- It does not train a real ML classifier.
- It does not prove the cause of a hotspot.
- It does not provide emergency/fire-service decisions.


Those are the next development stages.
