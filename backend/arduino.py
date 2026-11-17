
import serial
import json
import time
from datetime import datetime
from database import save_sensor_data

# Change COM3 to the port shown in Arduino IDE
SERIAL_PORT = "COM3"
BAUD_RATE = 115200

def start_sensor():
    print("PRECISION AGRICULTURE")
    print("Connecting to ESP32...")

    try:
        esp32 = serial.Serial(
            SERIAL_PORT,
            BAUD_RATE,
            timeout=3
        )

        time.sleep(2)
        print("ESP32 connected successfully!")

        while True:
            line = esp32.readline().decode(
                "utf-8", errors="ignore"
            ).strip()

            if not line:
                continue

            try:
                data = json.loads(line)

                sensor_data = {
                    "timestamp": datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                    "temperature": float(data["temperature"]),
                    "humidity": float(data["humidity"]),
                    "soil_moisture": float(data["soil_moisture"]),
                    "ph": float(data["soil_ph"])
                }

                print("LIVE ESP32 DATA:", sensor_data)

                if save_sensor_data(sensor_data):
                    print("Saved to MySQL successfully!")

            except (json.JSONDecodeError, KeyError, ValueError) as error:
                print("Invalid sensor data:", line, error)

    except serial.SerialException as error:
        print("ESP32 connection error:", error)

    finally:
        if 'esp32' in locals() and esp32.is_open:
            esp32.close()


if __name__ == "__main__":
    start_sensor()
