from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import requests
from collections import Counter
import os
import json
from werkzeug.utils import secure_filename
from pathlib import Path

# ───────────────────────────
# Flask + SQLAlchemy setup
# ───────────────────────────

app = Flask(__name__)

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///ticktracker.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ───────────────────────────
# Modèle SQLAlchemy
# ───────────────────────────

class TickReport(db.Model):
    __tablename__ = "tick_reports"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String, nullable=False)          # "YYYY-MM-DD" (ou ISO)
    city = db.Column(db.String, nullable=False)
    environment = db.Column(db.String)
    host = db.Column(db.String, nullable=False)
    species = db.Column(db.String)
    latin_name = db.Column(db.String)
    severity = db.Column(db.String)
    notes = db.Column(db.Text)
    email = db.Column(db.String)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    image_filename = db.Column(db.String)

    def to_dict_for_sightings(self):
        return {
            "date": self.date,
            "city": self.city,
            "location": self.city,          # ✅ pour compatibilité frontend (city || location)
            "species": self.species,
            "latinName": self.latin_name,
            "source": "user",
        }

# 🔴 CRÉER LES TABLES DÈS LE CHARGEMENT DU MODULE
with app.app_context():
    db.create_all()
    print("✅ Tables SQLite vérifiées / créées")

# ───────────────────────────
# Data sources
# ───────────────────────────

API_BASE = "https://dev-task.elancoapps.com/data"  # tu peux le laisser
BASE_DIR = Path(__file__).resolve().parent
LOCAL_JSON_PATH = BASE_DIR / "data" / "tick_sightings.json"

# ───────────────────────────
# Helpers
# ───────────────────────────

def load_local_sightings():
    """Load tick sightings from a local JSON file as fallback."""
    if not LOCAL_JSON_PATH.exists():
        print(f"⚠️ Local JSON not found: {LOCAL_JSON_PATH}")
        return []

    try:
        with LOCAL_JSON_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            print("⚠️ Local JSON must be a list of sightings")
            return []
    except Exception as e:
        print("❌ Error reading local JSON:", e)
        return []

def normalize_sighting(s: dict) -> dict:
    """Make sure each sighting has fields frontend expects."""
    # latinName
    if "latinName" not in s and "latin_name" in s:
        s["latinName"] = s["latin_name"]

    # location / city (frontend uses location || city)
    if "location" not in s and "city" in s:
        s["location"] = s["city"]
    if "city" not in s and "location" in s:
        s["city"] = s["location"]

    # date as string
    if "date" in s:
        s["date"] = str(s["date"])

    return s

def get_combined_sightings():
    # 1) Try Elanco API, fallback to local JSON
    elanco = []
    try:
        r = requests.get(f"{API_BASE}/tick-sightings", timeout=5)
        r.raise_for_status()
        elanco = r.json() or []
        print(f"✅ Loaded from Elanco API: {len(elanco)} sightings")
    except Exception as e:
        print("⚠️ Elanco API failed, using local JSON:", e)
        elanco = load_local_sightings()
        print(f"✅ Loaded from local JSON: {len(elanco)} sightings")

    for s in elanco:
        normalize_sighting(s)
        s["source"] = "elanco"

    # 2) User reports
    reports = TickReport.query.order_by(TickReport.date.desc()).all()
    user_data = [r.to_dict_for_sightings() for r in reports]

    print(f"ℹ️ User reports in DB: {len(user_data)}")

    # 3) merge
    return elanco + user_data

# ───────────────────────────
# PAGES HTML
# ───────────────────────────

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/map")
def map_page():
    return render_template("map.html")

@app.route("/species")
def species_page():
    all_sightings = get_combined_sightings()
    counts_by_latin = {}
    for s in all_sightings:
        latin = s.get("latinName")
        if latin:
            counts_by_latin[latin] = counts_by_latin.get(latin, 0) + 1
    return render_template("species.html", counts=counts_by_latin)

@app.route("/report")
def report_page():
    return render_template("report.html")

# ───────────────────────────
# API : enregistrer un report
# ───────────────────────────

@app.route("/api/report", methods=["POST"])
def api_report():
    # ✅ Support multipart/form-data (form + image)
    if "multipart/form-data" in (request.content_type or ""):
        form = request.form
        file = request.files.get("image")

        date = form.get("date")
        city = form.get("city")
        host = form.get("host")

        if not date or not city or not host:
            return jsonify({"success": False, "error": "Missing required fields"}), 400

        image_filename = None
        if file and file.filename:
            filename = secure_filename(file.filename)
            unique_name = f"{datetime.utcnow().timestamp()}_{filename}"
            upload_dir = os.path.join(app.static_folder, "uploads")
            os.makedirs(upload_dir, exist_ok=True)
            filepath = os.path.join(upload_dir, unique_name)
            file.save(filepath)
            image_filename = unique_name

        report = TickReport(
            date=date,
            city=city,
            environment=form.get("environment"),
            host=host,
            species=form.get("species"),
            latin_name=form.get("latinName"),
            severity=form.get("severity"),
            notes=form.get("notes"),
            email=form.get("email"),
            image_filename=image_filename,
        )

        db.session.add(report)
        db.session.commit()
        print(f"✅ Report saved (image={image_filename})")

        return jsonify({"success": True, "id": report.id})

    # ✅ Sinon on répond proprement
    return jsonify({"success": False, "error": "Content-Type must be multipart/form-data"}), 415

# ───────────────────────────
# API : données pour la MAP
# ───────────────────────────

@app.route("/api/sightings")
def api_sightings():
    data = get_combined_sightings()
    return jsonify(data)

# ───────────────────────────
# API : stats espèces
# ───────────────────────────

@app.route("/api/species-stats")
def api_species_stats():
    data = get_combined_sightings()

    counter = Counter()
    latin_by_spec = {}

    for s in data:
        species = s.get("species") or "Unknown species"
        latin = s.get("latinName") or ""
        counter[species] += 1
        if latin:
            latin_by_spec[species] = latin

    result = []
    for species, count in counter.items():
        latin = latin_by_spec.get(species, "")

        if count < 60:
            risk = "low"
        elif count <= 70:
            risk = "medium"
        else:
            risk = "high"

        result.append({
            "species": species,
            "latinName": latin,
            "count": count,
            "risk": risk
        })

    result.sort(key=lambda x: x["count"], reverse=True)
    return jsonify(result)

# ───────────────────────────
# ROUTE DEBUG
# ───────────────────────────

@app.route("/debug/reports")
def debug_reports():
    reports = TickReport.query.order_by(TickReport.created_at.desc()).all()
    return jsonify([{
        "id": r.id,
        "date": r.date,
        "city": r.city,
        "host": r.host,
        "species": r.species,
        "latinName": r.latin_name,
        "image_filename": r.image_filename,
        "notes": r.notes,
        "created_at": r.created_at.isoformat() if r.created_at else None
    } for r in reports])

# ───────────────────────────
# Run
# ───────────────────────────

if __name__ == "__main__":
    # ✅ IMPORTANT pour AWS/EC2 : écouter sur toutes les interfaces
    app.run(debug=True, host="0.0.0.0", port=5000)
