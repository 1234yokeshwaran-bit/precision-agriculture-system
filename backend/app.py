
import csv
import io
import json
import math
import os
import threading
import time
from datetime import datetime
from decimal import Decimal

import mysql.connector
import requests
import serial
from flask import Flask, Response, jsonify, render_template, request

from config import (
    DB_HOST,
    DB_USER,
    DB_PASSWORD,
    DB_NAME,
    SERIAL_PORT,
    BAUD_RATE
)

app = Flask(__name__)

# ---------------- DATABASE CONFIGURATION ----------------

DB_CONFIG = {
    "host": DB_HOST,
    "user": DB_USER,
    "password": DB_PASSWORD,
    "database": DB_NAME,
    "port": 3306
}

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")


def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)


def json_value(value):
    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")

    return value


def clean_row(row):
    if not row:
        return None

    return {
        key: json_value(value)
        for key, value in row.items()
    }


# ---------------- SAVE SENSOR DATA ----------------

def save_to_database(data):
    connection = get_db_connection()

    try:
        cursor = connection.cursor()

        sensor_ph = data.get("soil_ph", data.get("ph"))

        cursor.execute(
            """
            INSERT INTO agriculture_dataset
            (timestamp, temperature, humidity, soil_moisture, ph, raw_json)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                data.get(
                    "timestamp",
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ),
                float(data["temperature"]),
                float(data["humidity"]),
                float(data["soil_moisture"]),
                str(sensor_ph),
                json.dumps(data)
            )
        )

        connection.commit()
        print("Sensor data saved successfully!")

    finally:
        connection.close()


# ---------------- ESP32 SERIAL READING ----------------

def read_esp32():
    """Read JSON sensor data from ESP32 when hardware is available."""

    if not SERIAL_PORT:
        print("ESP32 serial connection is disabled.")
        return

    while True:
        try:
            print("Connecting to ESP32:", SERIAL_PORT)

            with serial.Serial(
                SERIAL_PORT,
                BAUD_RATE,
                timeout=2
            ) as esp:

                print("ESP32 connected.")
                time.sleep(2)

                while True:
                    line = esp.readline().decode(
                        "utf-8",
                        errors="ignore"
                    ).strip()

                    if not line:
                        continue

                    try:
                        data = json.loads(line)

                        required = [
                            "temperature",
                            "humidity",
                            "soil_moisture"
                        ]

                        for key in required:
                            data[key] = float(data[key])

                        data["soil_ph"] = float(
                            data.get("soil_ph", data.get("ph"))
                        )

                        values = [
                            data["temperature"],
                            data["humidity"],
                            data["soil_moisture"],
                            data["soil_ph"]
                        ]

                        if not all(math.isfinite(v) for v in values):
                            raise ValueError("Invalid sensor values")

                        if not 0 <= data["soil_ph"] <= 14:
                            print("Invalid pH reading")
                            continue

                        save_to_database(data)

                    except (
                        json.JSONDecodeError,
                        KeyError,
                        TypeError,
                        ValueError
                    ) as error:
                        print("Invalid ESP32 data:", error)

        except (
            serial.SerialException,
            mysql.connector.Error,
            OSError
        ) as error:
            print("ESP32 connection issue:", error)
            time.sleep(5)


# ---------------- LATEST SENSOR READING ----------------

def latest_sensor():
    connection = get_db_connection()

    try:
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                timestamp AS recorded_at,
                temperature,
                humidity,
                soil_moisture,
                ph AS soil_ph
            FROM agriculture_dataset
            ORDER BY timestamp DESC
            LIMIT 1
            """
        )

        row = cursor.fetchone()
        return clean_row(row)

    finally:
        connection.close()


@app.route("/api/latest")
def api_latest():
    try:
        row = latest_sensor()

        if row is None:
            return jsonify({
                "error": "No sensor readings found yet."
            }), 404

        return jsonify(row)

    except mysql.connector.Error as error:
        return jsonify({"error": str(error)}), 500


# ---------------- SENSOR HISTORY ----------------

@app.route("/api/history")
def api_history():
    try:
        hours = max(1, min(int(request.args.get("hours", 24)), 24 * 365))
        connection = get_db_connection()

        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT
                    timestamp AS recorded_at,
                    temperature,
                    humidity,
                    soil_moisture,
                    ph AS soil_ph
                FROM agriculture_dataset
                WHERE timestamp >= DATE_SUB(NOW(), INTERVAL %s HOUR)
                ORDER BY timestamp ASC
                """,
                (hours,)
            )
            rows = [clean_row(row) for row in cursor.fetchall()]
        finally:
            connection.close()

        return jsonify({"readings": rows})

    except (ValueError, mysql.connector.Error) as error:
        return jsonify({"error": str(error)}), 400


# ---------------- SENSOR STATISTICS ----------------

@app.route("/api/stats")
def api_stats():
    try:
        hours = max(
            1,
            min(int(request.args.get("hours", 24)), 24 * 365)
        )

        connection = get_db_connection()

        try:
            cursor = connection.cursor(dictionary=True)

            cursor.execute(
                """
                SELECT
                    COUNT(*) AS readings_count,
                    AVG(temperature) AS avg_temperature,
                    AVG(humidity) AS avg_humidity,
                    AVG(soil_moisture) AS avg_soil_moisture,
                    AVG(CAST(ph AS DECIMAL(5,2))) AS avg_soil_ph
                FROM agriculture_dataset
                WHERE timestamp >= DATE_SUB(NOW(), INTERVAL %s HOUR)
                """,
                (hours,)
            )

            row = clean_row(cursor.fetchone())

        finally:
            connection.close()

        return jsonify(row)

    except (ValueError, mysql.connector.Error) as error:
        return jsonify({"error": str(error)}), 400


# ---------------- CSV EXPORT ----------------

@app.route("/api/export")
def api_export():
    try:
        hours = max(
            1,
            min(int(request.args.get("hours", 24)), 24 * 365)
        )

        connection = get_db_connection()

        try:
            cursor = connection.cursor(dictionary=True)

            cursor.execute(
                """
                SELECT
                    timestamp AS recorded_at,
                    temperature,
                    humidity,
                    soil_moisture,
                    ph AS soil_ph
                FROM agriculture_dataset
                WHERE timestamp >= DATE_SUB(NOW(), INTERVAL %s HOUR)
                ORDER BY timestamp ASC
                """,
                (hours,)
            )

            rows = cursor.fetchall()

        finally:
            connection.close()

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            "Timestamp",
            "Temperature",
            "Humidity",
            "Soil Moisture",
            "Soil pH"
        ])

        for row in rows:
            writer.writerow([
                row["recorded_at"],
                row["temperature"],
                row["humidity"],
                row["soil_moisture"],
                row["soil_ph"]
            ])

        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={
                "Content-Disposition":
                f"attachment; filename=sensor_report_{hours}h.csv"
            }
        )

    except (ValueError, mysql.connector.Error) as error:
        return jsonify({"error": str(error)}), 400


# ---------------- CROP DATASET ----------------

def fetch_crops(search=""):
    connection = get_db_connection()

    try:
        cursor = connection.cursor(dictionary=True)

        query = """
            SELECT
                `Crop` AS crop,
                `Moisture(%)` AS moisture,
                `Soil_pH` AS soil_ph,
                `Temperature(C)` AS temperature
            FROM crop_dataset
        """

        if search:
            cursor.execute(
                query + " WHERE `Crop` LIKE %s ORDER BY `Crop`",
                (f"%{search}%",)
            )
        else:
            cursor.execute(query + " ORDER BY `Crop`")

        return [
            clean_row(row)
            for row in cursor.fetchall()
        ]

    finally:
        connection.close()


@app.route("/api/crops")
def api_crops():
    try:
        crops = fetch_crops(
            request.args.get("q", "").strip()
        )

        return jsonify({"crops": crops})

    except mysql.connector.Error as error:
        return jsonify({"error": str(error)}), 500


# ---------------- CROP RECOMMENDATION ENGINE ----------------

def calculate_recommendations(sensor, crops):
    fields = ("moisture", "soil_ph", "temperature")

    ranges = {}

    for field in fields:
        values = [float(crop[field]) for crop in crops]
        ranges[field] = max(values) - min(values) or 1.0

    sensor_values = {
        "moisture": float(sensor["soil_moisture"]),
        "soil_ph": float(sensor["soil_ph"]),
        "temperature": float(sensor["temperature"])
    }

    recommendations = []

    for crop in crops:
        distance = math.sqrt(
            sum(
                (
                    (sensor_values[field] - float(crop[field]))
                    / ranges[field]
                ) ** 2
                for field in fields
            ) / len(fields)
        )

        score = max(
            0.0,
            min(100.0, 100.0 * (1.0 - distance))
        )

        recommendations.append({
            "crop": crop["crop"],
            "match_score": round(score, 2),
            "required_moisture": crop["moisture"],
            "required_soil_ph": crop["soil_ph"],
            "required_temperature": crop["temperature"]
        })

    recommendations.sort(
        key=lambda item: item["match_score"],
        reverse=True
    )

    return recommendations


@app.route("/api/recommendations")
def api_recommendations():
    try:
        sensor = latest_sensor()

        if sensor is None:
            return jsonify({
                "error": "No sensor readings found yet."
            }), 404

        ph = float(sensor["soil_ph"])

        if not 0 <= ph <= 14:
            return jsonify({
                "error": "Invalid soil pH reading."
            }), 400

        crops = fetch_crops()

        if not crops:
            return jsonify({
                "error": "The crop_dataset table is empty."
            }), 404

        recommendations = calculate_recommendations(
            sensor,
            crops
        )

        return jsonify({
            "current_sensor_readings": sensor,
            "total_crops_compared": len(crops),
            "recommendations": recommendations[:5]
        })

    except (mysql.connector.Error, ValueError, TypeError) as error:
        return jsonify({"error": str(error)}), 500


# ---------------- AI AGRICULTURE CHAT ----------------

@app.route("/api/chat", methods=["POST"])
def api_chat():
    body = request.get_json(silent=True) or {}

    message = str(body.get("message", "")).strip()

    if not message:
        return jsonify({
            "error": "Please enter a question."
        }), 400

    if len(message) > 2000:
        return jsonify({
            "error": "Message is too long."
        }), 400

    try:
        sensor = latest_sensor()
        crops = fetch_crops()

        top_crops = []

        if sensor and crops:
            recommendations = calculate_recommendations(
                sensor,
                crops
            )

            top_crops = recommendations[:5]

        context = {
            "latest_sensor_readings": sensor,
            "top_crop_matches_from_database": top_crops
        }

        system_prompt = (
            "You are a careful precision agriculture assistant. "
            "Answer clearly and practically. "
            "Use the supplied sensor readings and crop matches. "
            "Do not invent sensor readings or claim that match scores "
            "are probabilities. Explain that crop suitability also "
            "depends on local climate, season and soil testing. "
            "NPK sensors are not used in this project. "
            "If sensor data is missing, say so.\n\n"
            "Project data:\n"
            + json.dumps(context, default=str)
        )

        response = requests.post(
            f"{OLLAMA_URL.rstrip('/')}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "stream": False,
                "messages": [
                    {
                        "role": "system",
                        "content": system_prompt
                    },
                    {
                        "role": "user",
                        "content": message
                    }
                ]
            },
            timeout=120
        )

        response.raise_for_status()

        answer = (
            response.json()
            .get("message", {})
            .get("content", "")
            .strip()
        )

        if not answer:
            raise RuntimeError("Ollama returned an empty response.")

        return jsonify({"answer": answer})

    except requests.exceptions.ConnectionError:
        return jsonify({
            "error": "Cannot connect to Ollama. Start Ollama and run: ollama run llama3.2"
        }), 503

    except requests.exceptions.Timeout:
        return jsonify({
            "error": "Ollama took too long to respond."
        }), 504

    except (
        requests.RequestException,
        mysql.connector.Error,
        RuntimeError,
        ValueError
    ) as error:
        return jsonify({
            "error": f"Chat assistant error: {error}"
        }), 500


# ---------------- HOME PAGE ----------------

@app.route("/")
def home():
    return render_template("index.html")


# ---------------- START FLASK SERVER ----------------

if __name__ == "__main__":
    print("====================================")
    print("PRECISION AGRICULTURE SYSTEM")
    print("Flask Server Starting...")
    print("Using simulated sensor data from MySQL")
    print("ESP32 serial reading is currently disabled")
    print("====================================")

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
        use_reloader=False
    )
