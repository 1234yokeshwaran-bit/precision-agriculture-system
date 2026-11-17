
import mysql.connector
from config import DB_HOST, DB_USER, DB_PASSWORD, DB_NAME

def get_connection():
    try:
        connection = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            port=3306
        )

        if connection.is_connected():
            return connection

    except mysql.connector.Error as e:
        print("Database connection error:", e)
        return None
    except mysql.connector.Error as error:
        print("Database Error:", error)

    return None


def save_sensor_data(data):
    connection = get_connection()

    if connection is None:
        return False

    try:
        cursor = connection.cursor()

        query = """
            INSERT INTO agriculture_dataset
            (timestamp, temperature, humidity, soil_moisture, ph, raw_json)
            VALUES (%s, %s, %s, %s, %s, %s)
        """

        values = (
            data["timestamp"],
            data["temperature"],
            data["humidity"],
            data["soil_moisture"],
            str(data["ph"]),
            None
        )

        cursor.execute(query, values)
        connection.commit()

        print("Sensor data saved successfully!")
        return True

    except mysql.connector.Error as error:
        print("Insert Error:", error)
        return False

    finally:
        cursor.close()
        connection.close()
