from flask import Flask, render_template, request, jsonify
import os, requests, pandas as pd
from io import StringIO
from datetime import date, timedelta

app = Flask(__name__)

# ============================================================
# NASA FIRMS CONFIGURATION 
# ============================================================

MAP_KEY = os.getenv("FIRMS_MAP_KEY", "4af2ed2b14c4a8024c9551104eadea12")
DEFAULT_BBOX = "84.5,22.5,86.5,24.5"
DEFAULT_CENTER = [23.3441, 85.3096]
MAX_DAYS = 30
CHUNK_DAYS = 5 

# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()
session.headers.update({"User-Agent": "Thermal-Source-Intelligence/1.0"})

# ============================================================
# RISK ANALYSIS
# ============================================================

def risk_analysis(row):
    """Prototype risk model; not an official NASA classification."""

    # --------------------------------------------------------
    # FRP
    # --------------------------------------------------------

    try:
        frp = float(row.get("frp", 0) or 0)
    except (TypeError, ValueError):
        frp = 0.0

    # --------------------------------------------------------
    # CONFIDENCE
    # --------------------------------------------------------

    raw_conf = row.get("confidence", "")
    try:
        conf = float(raw_conf)
    except (TypeError, ValueError):
        conf = {"l": 35, "n": 60, "h": 90}.get(
            str(raw_conf).strip().lower(), 50
        )

    # --------------------------------------------------------
    # BRIGHTNESS TEMPERATURE
    # --------------------------------------------------------

    try:
        bright_ti4 = float(row.get("bright_ti4", 0) or 0)
    except (TypeError, ValueError):
        bright_ti4 = 0.0

    # --------------------------------------------------------
    # FRP SCORE
    # --------------------------------------------------------

    frp_score = min(frp * 0.8, 60)

    # --------------------------------------------------------
    # CONFIDENCE SCORE
    # --------------------------------------------------------

    confidence_score = conf * 0.30

    # --------------------------------------------------------
    # BRIGHTNESS SCORE
    # --------------------------------------------------------

    if bright_ti4 >= 330:
        brightness_score = 15
    elif bright_ti4 >= 315:
        brightness_score = 10
    elif bright_ti4 >= 300:
        brightness_score = 5
    else:
        brightness_score = 0

    # --------------------------------------------------------
    # FINAL SCORE
    # --------------------------------------------------------

    score = round(
        min(frp_score + confidence_score + brightness_score, 100), 1
    )

    # --------------------------------------------------------
    # RISK LEVEL
    # --------------------------------------------------------

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
        "classification": classification
    }

# ============================================================
# FETCH ONE FIRMS CHUNK
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

# ============================================================
# GET FIRMS DATA
# ============================================================

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
    frames, remaining = [], days

    # --------------------------------------------------------
    # FETCH DATA IN 5-DAY CHUNKS
    # --------------------------------------------------------

    while remaining > 0:
        chunk = min(CHUNK_DAYS, remaining)

        # Try near-real-time VIIRS first
        try:
            df = fetch_firms_chunk(
                bbox, current.isoformat(), chunk, "VIIRS_SNPP_NRT"
            )
        except requests.RequestException:
            df = pd.DataFrame()

        # Fallback to standard processing
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

    # --------------------------------------------------------
    # COMBINE / DEDUPLICATE
    # --------------------------------------------------------

    if not frames:
        return []

    df = pd.concat(frames, ignore_index=True)
    dedupe_cols = [
        c for c in ["latitude", "longitude", "acq_date", "acq_time", "satellite"]
        if c in df.columns
    ]

    if dedupe_cols:
        df = df.drop_duplicates(subset=dedupe_cols)

    # --------------------------------------------------------
    # CONVERT TO JSON RECORDS
    # --------------------------------------------------------

    records = []

    for _, row in df.iterrows():
        try:
            lat, lon = float(row["latitude"]), float(row["longitude"])
        except (KeyError, TypeError, ValueError):
            continue

        analysis = risk_analysis(row)

        records.append({
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
            **analysis
        })

    return records

# ============================================================
# HOME PAGE
# ============================================================

@app.route("/")
def index():
    return render_template("index.html")

# ============================================================
# HOTSPOTS API
# ============================================================

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

        return jsonify({
            "ok": True,
            "count": len(data),
            "days_requested": days,
            "high_risk": counts["HIGH"],
            "medium_risk": counts["MEDIUM"],
            "low_risk": counts["LOW"],
            "hotspots": data,
            "note": (
                "FIRMS reports satellite thermal detections. "
                "The risk score shown here is a prototype analytical "
                "indicator based on thermal signal, confidence and "
                "brightness temperature. It is not an official NASA "
                "fire-risk or emergency determination."
            )
        })

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ============================================================
# PLACE SEARCH API
# ============================================================

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
            timeout=15
        )
        response.raise_for_status()
        return jsonify({"ok": True, "results": response.json()})

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ============================================================
# APPLICATION START
# ============================================================

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=6969)