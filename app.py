import requests
from flask import Flask, render_template, jsonify

app = Flask(__name__)
BASE_URL = "https://dev-task.elancoapps.com/data"

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/map")
def map_page():
    return render_template("map.html")

@app.route("/species")
def species():
    return render_template("species.html")

@app.route("/report")
def report():
    return render_template("report.html")

@app.route("/api/sightings")
def api_sightings():
    try:
        r = requests.get(f"{BASE_URL}/tick-sightings", timeout=5)
        r.raise_for_status()
        return jsonify(r.json())
    except requests.exceptions.RequestException as e:
        print(f"Erreur API: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, host="localhost", port=5000)
