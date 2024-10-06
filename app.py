from flask import Flask, request, jsonify, send_file
from werkzeug.utils import secure_filename
from flask_cors import CORS
import json
import os
import uuid  # Import the uuid module
import math
import psycopg2
from psycopg2.extras import RealDictCursor
import firebase_admin
from firebase_admin import credentials, storage, initialize_app
from datetime import timedelta

app = Flask(__name__)
CORS(app)

# Initialize the Firebase Admin SDK
cred = credentials.Certificate('aimim-2afab-firebase-adminsdk-8gpgx-7e19be3275.json')
initialize_app(cred, {
    'projectId': 'aimim-2afab',
    'storageBucket': 'aimim-2afab.appspot.com'  # Replace with your actual bucket name
})

bucket = storage.bucket()

# PostgreSQL connection parameters
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
    cursor = conn.cursor()
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                        id SERIAL PRIMARY KEY,
                        phone_number TEXT,
                        username TEXT UNIQUE,
                        password TEXT)''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS surveys (
                        id SERIAL PRIMARY KEY,
                        name TEXT,
                        questions TEXT)''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS survey_responses (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER REFERENCES users(id),
                        survey_id INTEGER REFERENCES surveys(id) ON DELETE CASCADE,
                        responses TEXT,
                        location TEXT,
                        voice_recording_path TEXT)''')

    conn.commit()
    cursor.close()
    conn.close()

# Assuming you have a function to get the database connection
def get_db_connection():
    conn = psycopg2.connect(**db_params)
    return conn

@app.route('/register', methods=['POST'])
def register():
    try:
        data = request.json
        print("Received data:", data)  # Debugging: log the incoming data

        # Extracting fields from JSON payload
        phone_number = data.get('phoneNumber')
        username = data.get('username')
        password = data.get('password')

        # Check if phone_number exists
        if not phone_number:
            return jsonify({'error': 'Phone number is required'}), 400

        # Establish database connection and create cursor
        conn = get_db_connection()
        cursor = conn.cursor()

        # Check if the phone number already exists in the database
        cursor.execute("SELECT id FROM users WHERE phone_number = %s", (phone_number,))
        existing_user = cursor.fetchone()

        if existing_user:
            cursor.close()
            conn.close()  # Close connection if user exists
            return jsonify({'error': 'Phone number already registered'}), 400

        # Insert the new user and return the 'id'
        cursor.execute("INSERT INTO users (phone_number, username, password) VALUES (%s, %s, %s) RETURNING id", 
                       (phone_number, username, password))
        user_id = cursor.fetchone()[0]
        conn.commit()

        # Close cursor and connection
        cursor.close()
        conn.close()

        return jsonify({'message': 'User registered successfully', 'user_id': user_id}), 201

    except Exception as e:
        print(f"Error: {str(e)}")  # Log the error for debugging
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()
        return jsonify({'error': 'Registration failed'}), 500

# Login for users
@app.route('/login', methods=['POST'])
def login():
    data = request.json
    username = data['username']
    password = data['password']

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    cursor.execute("SELECT id, username FROM users WHERE username = %s AND password = %s", (username, password))
    user = cursor.fetchone()

    cursor.close()
    conn.close()

    if user:
        return jsonify({"success": True, "user_id": user['id'], "message": "Login successful"})
    else:
        return jsonify({"success": False, "message": "Invalid credentials"})

# Create a new survey
@app.route('/surveys', methods=['POST'])
def create_survey():
    data = request.json
    name = data['name']
    questions = json.dumps(data['questions'])  # Store as JSON string

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("INSERT INTO surveys (name, questions) VALUES (%s, %s)", (name, questions))
    conn.commit()

    cursor.close()
    conn.close()

    return jsonify({"success": True, "message": "Survey created successfully"})

# Get a list of all available surveys
@app.route('/surveys', methods=['GET'])
def get_surveys():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    cursor.execute("SELECT * FROM surveys")
    surveys = cursor.fetchall()

    cursor.close()
    conn.close()

    return jsonify({"surveys": surveys})

# Get a specific survey by ID
@app.route('/surveys/<int:survey_id>', methods=['GET'])
def get_survey(survey_id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    cursor.execute("SELECT * FROM surveys WHERE id = %s", (survey_id,))
    survey = cursor.fetchone()

    cursor.close()
    conn.close()

    if survey:
        survey['questions'] = json.loads(survey['questions'])  # Parse questions
        return jsonify(survey)
    else:
        return jsonify({"error": "Survey not found"}), 404

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

# Route to handle file upload
@app.route('/upload', methods=['POST'])
def upload_file():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file part in the request'}), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        # Secure the filename and prepare for upload
        filename = secure_filename(file.filename)
        
        # Create a unique filename to avoid overwriting (optional but recommended)
        unique_filename = f"{str(uuid.uuid4())}_{filename}"
        
        # Reference Firebase Storage bucket
        blob = bucket.blob(f"voice_recordings/{unique_filename}")

        # Upload file from Flask's file object
        blob.upload_from_file(file)

        # Generate a public URL for the uploaded file
        blob.make_public()  # Makes the file publicly accessible
        
        file_url = blob.public_url
        
        # Return success response with the file URL
        return jsonify({'message': 'File uploaded successfully', 'file_url': file_url}), 200

    except Exception as e:
        print(f"Error during file upload: {str(e)}")  # Log for debugging
        return jsonify({'error': 'File upload failed', 'details': str(e)}), 500

# Submit survey responses
@app.route('/submit_survey', methods=['POST'])
def submit_survey():
    data = request.json
    user_id = data['user_id']
    survey_id = data['survey_id']
    responses = json.dumps(data['responses'])  # Store responses as JSON string
    location = data.get('location')
    voice_recording_url = data.get('voice_recording_url')  # Get the URL from the uploaded recording

    location_data = json.loads(location) if location else None

    conn = get_db_connection()
    cursor = conn.cursor()

    # Insert the survey response along with the voice recording URL
    cursor.execute("INSERT INTO survey_responses (user_id, survey_id, responses, location, voice_recording_path) VALUES (%s, %s, %s, %s, %s)", 
                   (user_id, survey_id, responses, location, voice_recording_url))
    conn.commit()

    cursor.close()
    conn.close()

    return jsonify({"success": True, "message": "Survey response submitted successfully"})

# Delete a survey
@app.route('/surveys/<int:survey_id>', methods=['DELETE'])
def delete_survey(survey_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM surveys WHERE id = %s", (survey_id,))
    conn.commit()

    cursor.close()
    conn.close()

    return jsonify({"success": True, "message": "Survey deleted successfully"})

# Get all survey responses for a specific survey
@app.route('/surveys/<int:survey_id>/responses', methods=['GET'])
def get_survey_responses(survey_id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    cursor.execute("SELECT * FROM survey_responses WHERE survey_id = %s", (survey_id,))
    responses = cursor.fetchall()

    cursor.close()
    conn.close()

    return jsonify({"responses": responses})

if __name__ == '__main__':
    init_db()  # Create database tables on startup
    app.run(debug=True, host='0.0.0.0', port=5000)  # Change host and port as needed
