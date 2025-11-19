import requests
from flask import Flask, render_template, jsonify

app = Flask(__name__)
BASE_URL = "https://dev-task.elancoapps.com/data"

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/api/sightings")
def api_sightings():
    r = requests.get(f"{BASE_URL}/tick-sightings", timeout=5)
    r.raise_for_status()
    return jsonify(r.json())

if __name__ == "__main__":
    app.run(debug=True)
