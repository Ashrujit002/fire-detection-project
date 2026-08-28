from flask import Flask, render_template, request, jsonify
import os
import requests
import pandas as pd
import joblib
from io import StringIO
from datetime import date, timedelta

app = Flask(__name__)



# ============================================================
# CONFIGURATION
# ============================================================

MAP_KEY = os.getenv("FIRMS_MAP_KEY", "4af2ed2b14c4a8024c9551104eadea12")
DEFAULT_BBOX = "87.5,21.8,89.0,23.5"
DEFAULT_CENTER = [22.5726, 88.3639]
MAX_DAYS = 30
CHUNK_DAYS = 5

MODEL_PATH = os.path.join(os.path.dirname(__file__), "fire_risk_model.pkl")
MODEL_FEATURES = [
    "frp",
    "confidence_numeric",
    "bright_ti4",
    "bright_ti5",
    "scan",
    "track",
]

session = requests.Session()
session.headers.update({"User-Agent": "Thermal-Source-Intelligence/1.0"})

# Cache reverse-geocoding results so repeated hotspot clicks do not create
# unnecessary OpenStreetMap requests.
AREA_TYPE_CACHE = {}


# ============================================================
# EXISTING PROTOTYPE ANALYSIS
# ============================================================

def risk_analysis(row):
    """Prototype analytical score used as the initial training label.

    Important: this is NOT an official NASA fire-risk classification.
    For a scientifically validated predictive model, replace these
    generated labels with real historical fire/no-fire ground truth.
    """

    try:
        frp = float(row.get("frp", 0) or 0)
    except (TypeError, ValueError):
        frp = 0.0

    raw_conf = row.get("confidence", "")
    try:
        conf = float(raw_conf)
    except (TypeError, ValueError):
        conf = {"l": 35, "n": 60, "h": 90}.get(
            str(raw_conf).strip().lower(), 50
        )

    try:
        bright_ti4 = float(row.get("bright_ti4", 0) or 0)
    except (TypeError, ValueError):
        bright_ti4 = 0.0

    frp_score = min(frp * 0.8, 60)
    confidence_score = conf * 0.30

    if bright_ti4 >= 330:
        brightness_score = 15
    elif bright_ti4 >= 315:
        brightness_score = 10
    elif bright_ti4 >= 300:
        brightness_score = 5
    else:
        brightness_score = 0

    score = round(
        min(frp_score + confidence_score + brightness_score, 100), 1
    )

    if score >= 65:
        level = "HIGH"
        classification = "Strong thermal anomaly"
    elif score >= 35:
        level = "MEDIUM"
        classification = "Moderate thermal anomaly"
    else:
        level = "LOW"
        classification = "Lower-intensity thermal anomaly"

    return {
        "risk_score": score,
        "risk_level": level,
        "classification": classification,
    }


# ============================================================
# ML HELPERS
# ============================================================

def confidence_to_number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return {"l": 35.0, "n": 60.0, "h": 90.0}.get(
            str(value).strip().lower(), 50.0
        )


def make_ml_features(row):
    """Convert one FIRMS row into the same features used for training."""
    def number(name):
        try:
            value = float(row.get(name, 0) or 0)
            return value if pd.notna(value) else 0.0
        except (TypeError, ValueError):
            return 0.0

    return {
        "frp": number("frp"),
        "confidence_numeric": confidence_to_number(row.get("confidence", "")),
        "bright_ti4": number("bright_ti4"),
        "bright_ti5": number("bright_ti5"),
        "scan": number("scan"),
        "track": number("track"),
    }


def predict_with_ml(row):
    """Predict the trained ML class. Returns None if model is unavailable."""
    if not os.path.exists(MODEL_PATH):
        return None

    try:
        model = joblib.load(MODEL_PATH)
        features = make_ml_features(row)
        X = pd.DataFrame([features], columns=MODEL_FEATURES)

        prediction = str(model.predict(X)[0])
        probabilities = {}

        if hasattr(model, "predict_proba"):
            probs = model.predict_proba(X)[0]
            for cls, prob in zip(model.classes_, probs):
                probabilities[str(cls)] = round(float(prob) * 100, 1)

        confidence = probabilities.get(prediction)

        return {
            "ml_risk_level": prediction,
            "ml_confidence": confidence,
            "ml_probabilities": probabilities,
        }
    except Exception:
        return None


# ============================================================
# FIRMS DATA
# ============================================================

def fetch_firms_chunk(bbox, start_date, days, source="VIIRS_SNPP_NRT"):
    url = (
        f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
        f"{MAP_KEY}/{source}/{bbox}/{days}/{start_date}"
    )

    response = session.get(url, timeout=45)
    response.raise_for_status()

    if not response.text.strip():
        return pd.DataFrame()

    return pd.read_csv(StringIO(response.text))


def get_firms_data(bbox=DEFAULT_BBOX, days=1):
    if not MAP_KEY:
        raise RuntimeError("NASA FIRMS MAP_KEY is not configured.")

    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 1

    days = max(1, min(days, MAX_DAYS))
    today = date.today()
    current = today - timedelta(days=days - 1)

    frames = []
    remaining = days

    while remaining > 0:
        chunk = min(CHUNK_DAYS, remaining)

        try:
            df = fetch_firms_chunk(
                bbox, current.isoformat(), chunk, "VIIRS_SNPP_NRT"
            )
        except requests.RequestException:
            df = pd.DataFrame()

        if df.empty:
            try:
                df = fetch_firms_chunk(
                    bbox, current.isoformat(), chunk, "VIIRS_SNPP_SP"
                )
            except requests.RequestException:
                df = pd.DataFrame()

        if not df.empty:
            frames.append(df)

        current += timedelta(days=chunk)
        remaining -= chunk

    if not frames:
        return []

    df = pd.concat(frames, ignore_index=True)

    dedupe_cols = [
        c for c in
        ["latitude", "longitude", "acq_date", "acq_time", "satellite"]
        if c in df.columns
    ]

    if dedupe_cols:
        df = df.drop_duplicates(subset=dedupe_cols)

    records = []

    for _, row in df.iterrows():
        try:
            lat = float(row["latitude"])
            lon = float(row["longitude"])
        except (KeyError, TypeError, ValueError):
            continue

        analysis = risk_analysis(row)
        ml = predict_with_ml(row)

        record = {
            "latitude": lat,
            "longitude": lon,
            "acq_date": str(row.get("acq_date", "")),
            "acq_time": str(row.get("acq_time", "")),
            "satellite": str(row.get("satellite", "VIIRS")),
            "instrument": str(row.get("instrument", "")),
            "confidence": row.get("confidence", ""),
            "frp": row.get("frp", ""),
            "bright_ti4": row.get("bright_ti4", ""),
            "bright_ti5": row.get("bright_ti5", ""),
            "daynight": str(row.get("daynight", "")),
            "scan": row.get("scan", ""),
            "track": row.get("track", ""),
            **analysis,
        }

        if ml:
            record.update(ml)
        else:
            record.update({
                "ml_risk_level": None,
                "ml_confidence": None,
                "ml_probabilities": {},
            })

        records.append(record)

    return records


# ============================================================
# AREA TYPE / REVERSE GEOCODING
# ============================================================

def classify_area_type(reverse_data):
    address = reverse_data.get("address", {}) or {}
    osm_type = str(reverse_data.get("type", "")).lower()
    osm_class = str(reverse_data.get("class", "")).lower()
    text = " ".join(
        [
            str(reverse_data.get("display_name", "")),
            osm_type,
            osm_class,
            " ".join(str(v) for v in address.values()),
        ]
    ).lower()

    # More specific land-use signals first.
    if any(x in text for x in [
        "forest", "wood", "protected area", "national park", "reserve"
    ]):
        return "Forest", "🌲"

    if any(x in text for x in [
        "farm", "farmland", "agricultural", "orchard", "plantation",
        "crop", "village"
    ]):
        return "Farming / Agriculture", "🌾"

    if any(x in text for x in [
        "industrial", "factory", "manufacturing", "warehouse", "works"
    ]):
        return "Factory / Industrial", "🏭"

    if any(x in text for x in [
        "residential", "housing", "apartments", "neighbourhood",
        "suburb", "locality"
    ]):
        return "Locality / Residential", "🏘️"

    if any(x in text for x in [
        "commercial", "retail", "shop", "market", "office"
    ]):
        return "Commercial", "🏬"

    if any(x in text for x in [
        "highway", "road", "motorway", "trunk", "junction"
    ]):
        return "Road / Transport", "🛣️"

    if any(x in text for x in [
        "wetland", "marsh", "river", "lake", "reservoir", "water"
    ]):
        return "Wetland / Water", "🌊"

    if any(x in text for x in [
        "grassland", "meadow", "scrub", "heath", "barren", "bare"
    ]):
        return "Open / Barren Land", "🏞️"

    if osm_type in {"city", "town", "city_block"}:
        return "Urban", "🏙️"

    return "Unknown", "❓"


def get_area_type(lat, lon):
    key = (round(float(lat), 5), round(float(lon), 5))

    if key in AREA_TYPE_CACHE:
        return AREA_TYPE_CACHE[key]

    response = session.get(
        "https://nominatim.openstreetmap.org/reverse",
        params={
            "lat": key[0],
            "lon": key[1],
            "format": "jsonv2",
            "zoom": 18,
            "addressdetails": 1,
            "extratags": 1,
        },
        headers={"User-Agent": "Thermal-Source-Intelligence/1.0"},
        timeout=15,
    )
    response.raise_for_status()

    area_type, icon = classify_area_type(response.json())

    result = {
        "area_type": area_type,
        "icon": icon,
        "label": "OpenStreetMap context",
    }

    AREA_TYPE_CACHE[key] = result
    return result



# ============================================================
# SMART AREA TYPE DETECTION
# ============================================================

import math


def distance_km(lat1, lon1, lat2, lon2):

    R = 6371.0

    p1 = math.radians(lat1)
    p2 = math.radians(lat2)

    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)

    a = (
        math.sin(dp / 2) ** 2
        + math.cos(p1)
        * math.cos(p2)
        * math.sin(dl / 2) ** 2
    )

    return 2 * R * math.asin(math.sqrt(a))


def area_result(name, icon, description, confidence, source):

    return {
        "name": name,
        "icon": icon,
        "description": description,
        "confidence": round(confidence, 1),
        "source": source
    }


def classify_osm_tags(tags):

    tags = {
        str(k).lower(): str(v).lower()
        for k, v in (tags or {}).items()
    }

    landuse = tags.get("landuse", "")
    natural = tags.get("natural", "")
    industrial = tags.get("industrial", "")
    building = tags.get("building", "")
    place = tags.get("place", "")
    amenity = tags.get("amenity", "")
    leisure = tags.get("leisure", "")


    # ========================================================
    # FOREST
    # ========================================================

    if landuse in {
        "forest",
        "wood"
    }:

        return (
            "Forest",
            "🌲",
            "The location is associated with a mapped forest or woodland area."
        )


    if natural in {
        "wood",
        "forest"
    }:

        return (
            "Forest",
            "🌲",
            "The location is associated with a mapped woodland or forest area."
        )


    # ========================================================
    # FARMING
    # ========================================================

    if landuse in {
        "farmland",
        "farm",
        "farmyard",
        "orchard",
        "vineyard",
        "plant_nursery",
        "greenhouse_horticulture",
        "allotments",
        "meadow"
    }:

        return (
            "Farming",
            "🌾",
            "The location is associated with agricultural or farming land."
        )


    # ========================================================
    # INDUSTRIAL
    # ========================================================

    if landuse == "industrial":

        return (
            "Factory / Industrial",
            "🏭",
            "The location is associated with an industrial land-use area."
        )


    if industrial:

        return (
            "Factory / Industrial",
            "🏭",
            "The location is associated with an industrial facility."
        )


    if building in {
        "industrial",
        "factory",
        "warehouse",
        "manufacture"
    }:

        return (
            "Factory / Industrial",
            "🏭",
            "The location is associated with an industrial or factory building."
        )


    # ========================================================
    # LOCALITY
    # ========================================================

    if place in {
        "city",
        "town",
        "village",
        "suburb",
        "neighbourhood",
        "hamlet",
        "quarter",
        "isolated_dwelling"
    }:

        return (
            "Locality",
            "🏘️",
            "The location is associated with a populated locality."
        )


    if landuse in {
        "residential",
        "commercial",
        "retail"
    }:

        return (
            "Locality",
            "🏘️",
            "The location is associated with a built-up or residential area."
        )


    if amenity:

        return (
            "Locality",
            "🏘️",
            "The location is associated with a populated or developed area."
        )


    if leisure in {
        "park",
        "playground",
        "pitch",
        "sports_centre"
    }:

        return (
            "Locality",
            "🏞️",
            "The location is associated with a developed recreational area."
        )


    return None


# ============================================================
# SMART AREA TYPE
# ============================================================

def detect_area_type(lat, lon):

    candidates = []


    # ========================================================
    # METHOD 1 — NOMINATIM REVERSE GEOCODING
    # ========================================================

    try:

        response = session.get(
            "https://nominatim.openstreetmap.org/reverse",

            params={
                "lat": lat,
                "lon": lon,
                "format": "json",
                "zoom": 18,
                "addressdetails": 1
            },

            headers={
                "User-Agent":
                    "Thermal-Source-Intelligence/1.0"
            },

            timeout=15
        )

        response.raise_for_status()

        data = response.json()

        address = data.get(
            "address",
            {}
        )

        osm_type = str(
            data.get("type", "")
        ).lower()

        osm_class = str(
            data.get("class", "")
        ).lower()

        display_name = str(
            data.get("display_name", "")
        ).lower()


        # ----------------------------------------------------
        # DIRECT OSM TYPE
        # ----------------------------------------------------

        direct = classify_osm_tags({

            "landuse": osm_type
                if osm_class == "landuse"
                else "",

            "natural": osm_type
                if osm_class == "natural"
                else "",

            "place": osm_type
                if osm_class == "place"
                else "",

            "building": osm_type
                if osm_class == "building"
                else "",

            "amenity": osm_type
                if osm_class == "amenity"
                else "",

            "industrial": osm_type
                if osm_class == "industrial"
                else ""

        })


        if direct:

            name, icon, description = direct

            candidates.append(
                (
                    95,
                    area_result(
                        name,
                        icon,
                        description,
                        95,
                        "OpenStreetMap reverse geocoding"
                    )
                )
            )


        # ----------------------------------------------------
        # ADDRESS BASED DETECTION
        # ----------------------------------------------------

        address_text = " ".join(

            str(v).lower()

            for v in address.values()

        )

        text = (
            display_name
            + " "
            + address_text
        )


        # FOREST KEYWORDS

        forest_words = [

            "forest",
            "wood",
            "woodland",
            "reserve forest",
            "national park",
            "wildlife",
            "sanctuary",
            "jungle",
            "reserved forest"

        ]

        if any(
            word in text
            for word in forest_words
        ):

            candidates.append(

                (
                    85,

                    area_result(

                        "Forest",
                        "🌲",

                        "The surrounding place information indicates a forest or woodland environment.",

                        85,

                        "OpenStreetMap place information"

                    )
                )
            )


        # FARMING KEYWORDS

        farming_words = [

            "farm",
            "farmland",
            "agriculture",
            "agricultural",
            "cultivation",
            "orchard",
            "plantation",
            "paddy",
            "rice field",
            "crop",
            "village farm",
            "khet",
            "farming"

        ]

        if any(
            word in text
            for word in farming_words
        ):

            candidates.append(

                (
                    82,

                    area_result(

                        "Farming",
                        "🌾",

                        "The surrounding place information indicates agricultural or farming land.",

                        82,

                        "OpenStreetMap place information"

                    )
                )
            )


        # INDUSTRIAL KEYWORDS

        industrial_words = [

            "industrial",
            "industry",
            "factory",
            "manufacturing",
            "warehouse",
            "plant",
            "industrial estate",
            "industrial area",
            "workshop"

        ]

        if any(
            word in text
            for word in industrial_words
        ):

            candidates.append(

                (
                    88,

                    area_result(

                        "Factory / Industrial",
                        "🏭",

                        "The surrounding place information indicates an industrial or factory area.",

                        88,

                        "OpenStreetMap place information"

                    )
                )
            )


        # LOCALITY KEYWORDS

        locality_words = [

            "city",
            "town",
            "village",
            "municipality",
            "suburb",
            "neighbourhood",
            "colony",
            "locality",
            "ward",
            "residential",
            "market",
            "bazaar",
            "road",
            "street"

        ]

        if any(
            word in text
            for word in locality_words
        ):

            candidates.append(

                (
                    70,

                    area_result(

                        "Locality",
                        "🏘️",

                        "The location appears to be within or near a populated or built-up locality.",

                        70,

                        "OpenStreetMap place information"

                    )
                )
            )


    except Exception as e:

        print(
            "Nominatim area detection:",
            e
        )


    # ========================================================
    # METHOD 2 — SEARCH NEARBY FEATURES
    # ========================================================

    overpass_query = f"""

    [out:json][timeout:25];

    (
        way(around:3000,{lat},{lon})["landuse"];
        way(around:3000,{lat},{lon})["natural"];
        way(around:3000,{lat},{lon})["industrial"];
        way(around:3000,{lat},{lon})["building"];
        way(around:3000,{lat},{lon})["place"];

        relation(around:3000,{lat},{lon})["landuse"];
        relation(around:3000,{lat},{lon})["natural"];
        relation(around:3000,{lat},{lon})["industrial"];
        relation(around:3000,{lat},{lon})["place"];
    );

    out tags center;

    """


    try:

        response = session.post(

            "https://overpass-api.de/api/interpreter",

            data=overpass_query,

            timeout=35

        )

        response.raise_for_status()

        elements = response.json().get(
            "elements",
            []
        )


        for element in elements:

            tags = element.get(
                "tags",
                {}
            )

            classified = classify_osm_tags(
                tags
            )

            if not classified:
                continue


            name, icon, description = classified


            # ------------------------------------------------
            # ESTIMATE DISTANCE
            # ------------------------------------------------

            center = element.get(
                "center",
                {}
            )

            feature_lat = center.get(
                "lat"
            )

            feature_lon = center.get(
                "lon"
            )


            if feature_lat is None:
                feature_lat = lat

            if feature_lon is None:
                feature_lon = lon


            distance = distance_km(

                lat,
                lon,

                float(feature_lat),
                float(feature_lon)

            )


            # ------------------------------------------------
            # DISTANCE SCORE
            # ------------------------------------------------

            if distance <= 0.5:

                confidence = 92

            elif distance <= 1:

                confidence = 86

            elif distance <= 2:

                confidence = 78

            else:

                confidence = 68


            candidates.append(

                (

                    confidence,

                    area_result(

                        name,
                        icon,
                        description,
                        confidence,
                        "OpenStreetMap nearby features"

                    )

                )
            )


    except Exception as e:

        print(
            "Overpass area detection:",
            e
        )


    # ========================================================
    # METHOD 3 — FALLBACK TO LOCALITY
    # ========================================================

    if candidates:

        candidates.sort(
            key=lambda x: x[0],
            reverse=True
        )

        return candidates[0][1]


    # ========================================================
    # FINAL FALLBACK
    # ========================================================

    return area_result(

        "Open / Unknown",

        "🌍",

        "No reliable land-use feature was found nearby. The location may be open land or an area with limited map coverage.",

        30,

        "Fallback"

    )


# ============================================================
# AREA TYPE API
# ============================================================

@app.route("/api/area-type")
def area_type():

    try:

        lat = float(
            request.args.get("lat")
        )

        lon = float(
            request.args.get("lon")
        )

    except (
        TypeError,
        ValueError
    ):

        return jsonify({

            "ok": False,

            "error":
                "Invalid latitude or longitude"

        }), 400


    try:

        result = detect_area_type(
            lat,
            lon
        )

        return jsonify({

            "ok": True,

            "area_type":
                result

        })


    except Exception as e:

        print(
            "Area type error:",
            e
        )

        return jsonify({

            "ok": True,

            "area_type": {

                "name":
                    "Locality",

                "icon":
                    "🏘️",

                "description":
                    "The area could not be precisely mapped, so the location is being treated as a general locality.",

                "confidence":
                    45,

                "source":
                    "Fallback classification"

            }

        })

# ============================================================
# ROUTES
# ============================================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/hotspots")
def hotspots():
    bbox = request.args.get("bbox", DEFAULT_BBOX)

    try:
        days = max(1, min(int(request.args.get("days", "1")), MAX_DAYS))
    except ValueError:
        days = 1

    try:
        data = get_firms_data(bbox, days)

        counts = {
            level: sum(x.get("risk_level") == level for x in data)
            for level in ("HIGH", "MEDIUM", "LOW")
        }

        ml_counts = {
            level: sum(x.get("ml_risk_level") == level for x in data)
            for level in ("HIGH", "MEDIUM", "LOW")
        }

        return jsonify({
            "ok": True,
            "count": len(data),
            "days_requested": days,
            "high_risk": counts["HIGH"],
            "medium_risk": counts["MEDIUM"],
            "low_risk": counts["LOW"],
            "ml_high_risk": ml_counts["HIGH"],
            "ml_medium_risk": ml_counts["MEDIUM"],
            "ml_low_risk": ml_counts["LOW"],
            "ml_model_available": os.path.exists(MODEL_PATH),
            "hotspots": data,
            "note": (
                "FIRMS reports satellite thermal detections. "
                "The prototype score uses thermal signal, confidence "
                "and brightness temperature. The ML model is trained "
                "from those initial analytical labels and is therefore "
                "a prototype thermal-classification model, not an "
                "official NASA fire-risk or emergency determination."
            ),
        })

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/ml-predict", methods=["POST"])
def ml_predict():
    """Direct ML prediction endpoint for frontend/API use."""
    if not os.path.exists(MODEL_PATH):
        return jsonify({
            "ok": False,
            "error": "ML model not trained yet. Run train_model.py first."
        }), 503

    payload = request.get_json(silent=True) or {}

    required = ["frp", "confidence", "bright_ti4", "bright_ti5", "scan", "track"]
    missing = [x for x in required if x not in payload]

    if missing:
        return jsonify({
            "ok": False,
            "error": f"Missing fields: {', '.join(missing)}"
        }), 400

    result = predict_with_ml(payload)

    if not result:
        return jsonify({
            "ok": False,
            "error": "Unable to run ML prediction."
        }), 500

    return jsonify({
        "ok": True,
        **result
    })




@app.route("/api/search")
def search_place():
    query = request.args.get("q", "").strip()

    if not query:
        return jsonify({"ok": False, "error": "Enter a place name."}), 400

    try:
        response = session.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 5},
            headers={"User-Agent": "Thermal-Source-Intelligence/1.0"},
            timeout=15,
        )

        response.raise_for_status()
        return jsonify({"ok": True, "results": response.json()})

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500



if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=6969)
