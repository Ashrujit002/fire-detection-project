"""
Train the prototype Random Forest model for the FIRMS project.

Run:
    python train_model.py

This downloads recent FIRMS observations for the configured bounding box,
creates initial labels using the project's existing analytical score,
trains a Random Forest classifier, evaluates it, and saves:

    fire_risk_model.pkl

IMPORTANT:
The initial labels are generated from the existing rule-based score.
Therefore this demonstrates a real ML training/deployment pipeline, but it
is NOT yet a scientifically validated future-fire prediction model.

For a genuine predictive model, replace the generated labels with historical
ground truth such as fire/no-fire observations for fixed locations and dates.
"""

import os
import requests
import pandas as pd
import joblib

from io import StringIO
from datetime import date, timedelta

from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
)

MAP_KEY = os.getenv("FIRMS_MAP_KEY", "4af2ed2b14c4a8024c9551104eadea12")
BBOX = os.getenv("FIRMS_BBOX", "84.5,22.5,86.5,24.5")
DAYS = 30
CHUNK_DAYS = 5

FEATURES = [
    "frp",
    "confidence_numeric",
    "bright_ti4",
    "bright_ti5",
    "scan",
    "track",
]

MODEL_PATH = os.path.join(os.path.dirname(__file__), "fire_risk_model.pkl")

session = requests.Session()
session.headers.update({"User-Agent": "Thermal-Source-Intelligence/1.0"})


def confidence_to_number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return {"l": 35.0, "n": 60.0, "h": 90.0}.get(
            str(value).strip().lower(), 50.0
        )


def number(value):
    try:
        value = float(value)
        return value if pd.notna(value) else 0.0
    except (TypeError, ValueError):
        return 0.0


def prototype_label(row):
    frp = number(row.get("frp"))
    conf = confidence_to_number(row.get("confidence"))
    bright_ti4 = number(row.get("bright_ti4"))

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

    score = min(frp_score + confidence_score + brightness_score, 100)

    if score >= 65:
        return "HIGH"
    if score >= 35:
        return "MEDIUM"
    return "LOW"


def fetch_chunk(start_date, days, source):
    url = (
        f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
        f"{MAP_KEY}/{source}/{BBOX}/{days}/{start_date}"
    )

    response = session.get(url, timeout=45)
    response.raise_for_status()

    if not response.text.strip():
        return pd.DataFrame()

    return pd.read_csv(StringIO(response.text))


def download_data():
    frames = []
    current = date.today() - timedelta(days=DAYS - 1)
    remaining = DAYS

    while remaining > 0:
        chunk = min(CHUNK_DAYS, remaining)
        print(f"Downloading FIRMS data: {current} ({chunk} days)")

        try:
            df = fetch_chunk(
                current.isoformat(), chunk, "VIIRS_SNPP_NRT"
            )
        except requests.RequestException:
            df = pd.DataFrame()

        if df.empty:
            try:
                df = fetch_chunk(
                    current.isoformat(), chunk, "VIIRS_SNPP_SP"
                )
            except requests.RequestException:
                df = pd.DataFrame()

        if not df.empty:
            frames.append(df)

        current += timedelta(days=chunk)
        remaining -= chunk

    if not frames:
        raise RuntimeError("No FIRMS data was downloaded.")

    df = pd.concat(frames, ignore_index=True)

    dedupe = [
        c for c in
        ["latitude", "longitude", "acq_date", "acq_time", "satellite"]
        if c in df.columns
    ]

    if dedupe:
        df = df.drop_duplicates(subset=dedupe)

    return df


def prepare_dataset(df):
    output = pd.DataFrame()

    output["frp"] = df.get("frp", 0).apply(number)
    output["confidence_numeric"] = df.get(
        "confidence", ""
    ).apply(confidence_to_number)
    output["bright_ti4"] = df.get("bright_ti4", 0).apply(number)
    output["bright_ti5"] = df.get("bright_ti5", 0).apply(number)
    output["scan"] = df.get("scan", 0).apply(number)
    output["track"] = df.get("track", 0).apply(number)

    output["target"] = df.apply(prototype_label, axis=1)

    return output.dropna(subset=FEATURES + ["target"])


def main():
    if not MAP_KEY:
        raise RuntimeError("Set FIRMS_MAP_KEY before training.")

    print("Downloading training data...")
    raw = download_data()

    print(f"Raw FIRMS rows: {len(raw)}")

    data = prepare_dataset(raw)

    print(f"Training rows: {len(data)}")
    print("\nClass distribution:")
    print(data["target"].value_counts())

    if data["target"].nunique() < 2:
        raise RuntimeError(
            "The dataset contains fewer than two classes. "
            "Collect more varied historical data."
        )

    X = data[FEATURES]
    y = data["target"]

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.20,
        random_state=42,
        stratify=y,
    )

    model = RandomForestClassifier(
        n_estimators=300,
        max_depth=12,
        min_samples_leaf=2,
        random_state=42,
        class_weight="balanced",
        n_jobs=-1,
    )

    print("\nTraining Random Forest...")
    model.fit(X_train, y_train)

    predictions = model.predict(X_test)

    print("\n==============================")
    print("MODEL EVALUATION")
    print("==============================")
    print(f"Accuracy: {accuracy_score(y_test, predictions):.4f}")
    print("\nClassification report:")
    print(classification_report(y_test, predictions, zero_division=0))
    print("Confusion matrix:")
    print(confusion_matrix(y_test, predictions))

    print("\nFeature importance:")
    for feature, importance in sorted(
        zip(FEATURES, model.feature_importances_),
        key=lambda x: x[1],
        reverse=True,
    ):
        print(f"{feature:22s}: {importance:.4f}")

    joblib.dump(model, MODEL_PATH)

    print("\nModel saved:")
    print(MODEL_PATH)
    print("\nNow start Flask with:")
    print("python app.py")


if __name__ == "__main__":
    main()
