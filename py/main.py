from flask import Flask, redirect, request, jsonify
from dotenv import load_dotenv
import os
import base64
import requests
import json
import sqlite3

load_dotenv()

client_id = os.getenv("CLIENT_ID")
client_secret = os.getenv("CLIENT_SECRET")
redirect_uri = "http://localhost:5000/callback"

scopes = "user-read-private user-read-email user-top-read"
spotify_auth_url = f"https://accounts.spotify.com/authorize?response_type=code&client_id={client_id}&scope={scopes}&redirect_uri={redirect_uri}"

app = Flask(__name__)

def init_db():
    conn = sqlite3.connect("spotify_preferences.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            spotify_user_id TEXT UNIQUE NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS top_artists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            user_id INTEGER,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS top_tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            artist TEXT NOT NULL,
            user_id INTEGER,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.commit()
    conn.close()

init_db()

def get_token():
    try:
        auth_string = f"{client_id}:{client_secret}"
        auth_bytes = auth_string.encode("utf-8")
        auth_base64 = base64.b64encode(auth_bytes).decode("utf-8")
        url = "https://accounts.spotify.com/api/token"
        headers = {
            "Authorization": f"Basic {auth_base64}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data = {"grant_type": "client_credentials"}
        result = requests.post(url, headers=headers, data=data)
        result.raise_for_status()
        return result.json().get("access_token")
    except requests.RequestException as e:
        print(f"Error getting token: {e}")
        return None

def get_auth_header(token):
    return {"Authorization": f"Bearer {token}"} if token else {}

def get_spotify_user_id(token):
    try:
        response = requests.get("https://api.spotify.com/v1/me", headers=get_auth_header(token))
        response.raise_for_status()
        return response.json().get("id")
    except requests.RequestException as e:
        print(f"Error retrieving Spotify user ID: {e}")
        return None

def get_top_items(endpoint, token, limit=3):
    try:
        url = f"https://api.spotify.com/v1/me/top/{endpoint}?limit={limit}"
        response = requests.get(url, headers=get_auth_header(token))
        response.raise_for_status()
        return response.json().get("items", [])
    except requests.RequestException as e:
        print(f"Error retrieving top {endpoint}: {e}")
        return []

def save_user_data(spotify_user_id, top_artists, top_tracks):
    if not spotify_user_id:
        print("Error: Missing Spotify user ID")
        return

    conn = sqlite3.connect("spotify_preferences.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM users WHERE spotify_user_id = ?", (spotify_user_id,))
    existing_user = cursor.fetchone()
    
    if not existing_user:
        cursor.execute("INSERT INTO users (spotify_user_id) VALUES (?)", (spotify_user_id,))
        conn.commit()
    
    user_id = cursor.execute("SELECT id FROM users WHERE spotify_user_id = ?", (spotify_user_id,)).fetchone()
    if not user_id:
        print("Error: User not found after insertion")
        conn.close()
        return
    user_id = user_id[0]
    
    for artist in top_artists:
        cursor.execute("INSERT INTO top_artists (name, user_id) VALUES (?, ?)", (artist.get("name"), user_id))
    for track in top_tracks:
        cursor.execute("INSERT INTO top_tracks (name, artist, user_id) VALUES (?, ?, ?)", (track.get("name"), track.get("artist"), user_id))
    
    conn.commit()
    conn.close()

@app.route('/login')
def login():
    return redirect(spotify_auth_url)

@app.route('/callback')
def callback():
    code = request.args.get('code')
    if not code:
        return jsonify({"error": "Authorization code missing"}), 400
    
    try:
        url = "https://accounts.spotify.com/api/token"
        headers = {
            "Authorization": f"Basic {base64.b64encode(f'{client_id}:{client_secret}'.encode()).decode()}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri
        }
        response = requests.post(url, headers=headers, data=data)
        response.raise_for_status()
        access_token = response.json().get('access_token')
    except requests.RequestException as e:
        return jsonify({"error": f"Failed to get access token: {e}"}), 400
    
    spotify_user_id = get_spotify_user_id(access_token)
    if not spotify_user_id:
        return jsonify({"error": "Could not retrieve user ID from Spotify"}), 400
    
    top_tracks = [{"name": t["name"], "artist": t["artists"][0]["name"]} for t in get_top_items("tracks", access_token, 10)]
    top_artists = [{"name": a["name"]} for a in get_top_items("artists", access_token, 10)]
    
    save_user_data(spotify_user_id, top_artists, top_tracks)
    return jsonify({"My favorite artists": top_artists, "My favorite tracks": top_tracks})

if __name__ == "__main__":
    app.run(debug=True)
