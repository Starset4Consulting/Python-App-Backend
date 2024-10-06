from flask import Flask, request, jsonify, send_file
from werkzeug.utils import secure_filename
from flask_cors import CORS
import json
import psycopg2
import os
import math
import firebase_admin
from firebase_admin import credentials, storage

app = Flask(__name__)
CORS(app)

# Initialize Firebase
cred = credentials.Certificate('path/to/your/serviceAccountKey.json')  # Update with your service account key path
firebase_admin.initialize_app(cred, {
    'storageBucket': 'your-bucket-name.appspot.com'  # Update with your Firebase Storage bucket name
})

# PostgreSQL database connection parameters
db_params = {
    'dbname': 'aimim',
    'user': 'aimim_user',  # Replace with your username
    'password': 'fhH2YntIUtHxicimP5M6RCpcu3AOmJMx',
    'host': 'dpg-cs10b0a3esus7399aghg-a.singapore-postgres.render.com',
    'port': '5432'
}

# Initialize the PostgreSQL database
def init_db():
    conn = psycopg2.connect(**db_params)
    conn.autocommit = True
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            phone_number TEXT,
            username TEXT UNIQUE,
            password TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS surveys (
            id SERIAL PRIMARY KEY,
            name TEXT,
            questions TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS survey_responses (
            id SERIAL PRIMARY KEY,
            user_id INTEGER,
            survey_id INTEGER,
            responses TEXT,
            location TEXT,
            voice_recording_path TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (survey_id) REFERENCES surveys(id)
        )
    ''')
    cursor.close()
    conn.close()

# Register a new user
@app.route('/register', methods=['POST'])
def register():
    data = request.json
    phone_number = data['phoneNumber']
    username = data['username']
    password = data['password']

    conn = psycopg2.connect(**db_params)
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
    if cursor.fetchone():
        return jsonify({"success": False, "message": "Username already exists."})

    cursor.execute("INSERT INTO users (phone_number, username, password) VALUES (%s, %s, %s)", 
                   (phone_number, username, password))
    conn.commit()

    cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
    user_id = cursor.fetchone()[0]
    cursor.close()
    conn.close()

    return jsonify({"success": True, "user_id": user_id, "message": "User registered successfully"})

# Login for users
@app.route('/login', methods=['POST'])
def login():
    data = request.json
    username = data['username']
    password = data['password']

    conn = psycopg2.connect(**db_params)
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM users WHERE username = %s AND password = %s", (username, password))
    user = cursor.fetchone()

    cursor.close()
    conn.close()

    if user:
        return jsonify({"success": True, "user_id": user[0], "message": "Login successful"})
    else:
        return jsonify({"success": False, "message": "Invalid credentials"})

# Create a new survey
@app.route('/surveys', methods=['POST'])
def create_survey():
    data = request.json
    name = data['name']
    questions = data['questions']

    conn = psycopg2.connect(**db_params)
    cursor = conn.cursor()

    cursor.execute("INSERT INTO surveys (name, questions) VALUES (%s, %s)", (name, json.dumps(questions)))
    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"success": True, "message": "Survey created successfully"})

# Get a list of all available surveys
@app.route('/surveys', methods=['GET'])
def get_surveys():
    conn = psycopg2.connect(**db_params)
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM surveys")
    surveys = cursor.fetchall()
    survey_list = [{"id": s[0], "name": s[1], "questions": json.loads(s[2])} for s in surveys]

    cursor.close()
    conn.close()
    return jsonify({"surveys": survey_list})

# Get a specific survey by ID
@app.route('/surveys/<int:survey_id>', methods=['GET'])
def get_survey(survey_id):
    conn = psycopg2.connect(**db_params)
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM surveys WHERE id = %s", (survey_id,))
    survey = cursor.fetchone()

    cursor.close()
    conn.close()

    if survey:
        return jsonify({
            "id": survey[0],
            "name": survey[1],
            "questions": json.loads(survey[2])
        })
    else:
        return jsonify({"error": "Survey not found"}), 404

# Delete a survey by ID
@app.route('/surveys/<int:survey_id>', methods=['DELETE'])
def delete_survey(survey_id):
    conn = psycopg2.connect(**db_params)
    cursor = conn.cursor()

    cursor.execute("DELETE FROM surveys WHERE id = %s", (survey_id,))
    conn.commit()

    if cursor.rowcount == 0:
        cursor.close()
        conn.close()
        return jsonify({"success": False, "message": "Survey not found"}), 404

    cursor.close()
    conn.close()
    return jsonify({"success": True, "message": "Survey deleted successfully"})

# Haversine formula for distance calculation
def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # Radius of the Earth in kilometers
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2 +
        math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * 
        math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

# Submit a survey response
@app.route('/submit_survey', methods=['POST'])
def submit_survey():
    data = request.json
    user_id = data['user_id']
    survey_id = data['survey_id']
    responses = data['responses']
    location = data.get('location')
    voice_recording_path = data.get('voice_recording_path')

    location_data = json.loads(location) if location else None

    if location_data:
        latitude = location_data['latitude']
        longitude = location_data['longitude']

        conn = psycopg2.connect(**db_params)
        cursor = conn.cursor()

        cursor.execute("SELECT location FROM survey_responses WHERE user_id = %s ORDER BY id DESC LIMIT 1", (user_id,))
        last_response = cursor.fetchone()
        
        if last_response:
            last_location = json.loads(last_response[0])
            last_latitude = last_location['latitude']
            last_longitude = last_location['longitude']
            
            distance = haversine(latitude, longitude, last_latitude, last_longitude)

            if distance < 0.005:
                return jsonify({"success": False, "message": "You cannot take multiple surveys in this location within 5 meters."})

    conn = psycopg2.connect(**db_params)
    cursor = conn.cursor()

    cursor.execute("INSERT INTO survey_responses (user_id, survey_id, responses, location, voice_recording_path) VALUES (%s, %s, %s, %s, %s)", 
                   (user_id, survey_id, json.dumps(responses), location, voice_recording_path))
    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"success": True, "message": "Survey response submitted successfully"})

# Upload voice recording to Firebase
@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'No file part'})

    file = request.files['file']

    if file.filename == '':
        return jsonify({'success': False, 'message': 'No selected file'})

    filename = secure_filename(file.filename)
    blob = storage.bucket().blob(filename)
    blob.upload_from_file(file)

    # Get the public URL of the uploaded file
    blob.make_public()
    return jsonify({'success': True, 'file_url': blob.public_url})

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
