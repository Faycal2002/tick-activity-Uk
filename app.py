from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import requests
from collections import Counter
import os
from werkzeug.utils import secure_filename

# ───────────────────────────
# Flask + SQLAlchemy setup
# ───────────────────────────

app = Flask(__name__)

# IMPORTANT : ce fichier sera créé dans le même dossier que app.py
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///ticktracker.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# ───────────────────────────
# Modèle SQLAlchemy
# ───────────────────────────

class TickReport(db.Model):
    __tablename__ = "tick_reports"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String, nullable=False)          # "YYYY-MM-DD"
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
            "species": self.species,
            "latinName": self.latin_name,
            "source": "user",
        }


# 🔴 CRÉER LES TABLES DÈS LE CHARGEMENT DU MODULE
with app.app_context():
    db.create_all()
    print("✅ Tables SQLite vérifiées / créées")


API_BASE = "https://dev-task.elancoapps.com/data"


# ───────────────────────────
# Helper : API Elanco + DB
# ───────────────────────────

def get_combined_sightings():
    # 1) API Elanco
    try:
        r = requests.get(f"{API_BASE}/tick-sightings", timeout=5)
        r.raise_for_status()
        elanco = r.json() or []
    except Exception as e:
        print("Erreur API Elanco:", e)
        elanco = []

    for s in elanco:
        s["source"] = "elanco"

    # 2) Reports utilisateur
    reports = TickReport.query.order_by(TickReport.date.desc()).all()
    user_data = [r.to_dict_for_sightings() for r in reports]

    print(f"ℹ️ Nombre de reports en DB : {len(user_data)}")

    # 3) fusion
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
    """
    Page species avec nombres dynamiques :
    on compte les sightings par nom latin (API + DB).
    """
    all_sightings = get_combined_sightings()

    counts_by_latin = {}
    for s in all_sightings:
        latin = s.get("latinName")
        if latin:
            counts_by_latin[latin] = counts_by_latin.get(latin, 0) + 1

    # On passe le dict "counts" au template
    return render_template("species.html", counts=counts_by_latin)


@app.route("/report")
def report_page():
    return render_template("report.html")


# ───────────────────────────
# API : enregistrer un report
# ───────────────────────────

@app.route("/api/report", methods=["POST"])
def api_report():
    # Si formulaire classique multipart (avec fichier)
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
            # nom unique
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
        print(f"✅ Report sauvegardé avec image={image_filename}")

        return jsonify({"success": True, "id": report.id})

    # fallback JSON (au cas où)
    data = request.get_json() or {}
    if not data.get("date") or not data.get("city") or not data.get("host"):
        return jsonify({"success": False, "error": "Missing required fields"}), 400

    report = TickReport(
        date=data.get("date"),
        city=data.get("city"),
        environment=data.get("environment"),
        host=data.get("host"),
        species=data.get("species"),
        latin_name=data.get("latinName"),
        severity=data.get("severity"),
        notes=data.get("notes"),
        email=data.get("email"),
    )
    db.session.add(report)
    db.session.commit()

    return jsonify({"success": True, "id": report.id})


# ───────────────────────────
# API : données pour la MAP
# ───────────────────────────

@app.route("/api/sightings")
def api_sightings():
    data = get_combined_sightings()
    return jsonify(data)


# ───────────────────────────
# API : stats espèces (si tu veux t'en servir ailleurs)
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
# ROUTE DEBUG pour voir ce qu'il y a en DB
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
        "created_at": r.created_at.isoformat() if r.created_at else None
    } for r in reports])


# ───────────────────────────
# Run
# ───────────────────────────

if __name__ == "__main__":
    app.run(debug=True, host="localhost", port=5000)
