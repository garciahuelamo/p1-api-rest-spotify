from flask import Flask, request, jsonify, session, redirect
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from dotenv import load_dotenv
import os

app = Flask(__name__)
app.secret_key = '123456'
app.config['SESSION_COOKIE_NAME'] = 'spotify_session'
load_dotenv("keys.env")


CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI")
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
SCOPE = 'user-read-recently-played user-top-read user-library-read'

sp_oauth = SpotifyOAuth(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    scope=SCOPE
)

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    spotify_id = db.Column(db.String(120), unique=True, nullable=False)
    access_token = db.Column(db.String(255), nullable=False)

    def __repr__(self):
        return f'<User {self.spotify_id}>'

class FavoriteArtist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    genres = db.Column(db.String(255))

    def __repr__(self):
        return f'<FavoriteArtist {self.name}>'

class FavoriteSong(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    artist = db.Column(db.String(255), nullable=False)
    album = db.Column(db.String(255))
    popularity = db.Column(db.Integer)

    def __repr__(self):
        return f'<FavoriteSong {self.title}>'

sp_oauth = SpotifyOAuth(client_id=CLIENT_ID, client_secret=CLIENT_SECRET, redirect_uri=REDIRECT_URI, scope=SCOPE)

with app.app_context():
    db.create_all()

@app.route("/register", methods=['POST'])
def register():
    data = request.get_json()
    spotify_id = data.get("spotify_id")
    email = data.get("email")
    password = data.get("password")

    if not spotify_id:
        return jsonify({"Error" : "Missing data"}), 400
    
    if User.query.filter_by(spotify_id=spotify_id).first() or User.query.filter_by(email=email).first():
        return jsonify({"Error" : "User or email was already registered"}), 409
    
    new_user = User(spotify_id=spotify_id, email=email)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()

    return jsonify({"message" : "User successfully created"}), 201

@app.route("/users/<string:username>", methods=['PUT'])
def update_users(username):

    if not request.is_json:
        return jsonify({"Error" : "Content-Type must be application/json"}), 415
    
    data = request.get_json()
    user = User.query.filter_by(username=username).first()

    if not user:
        return jsonify({"Error" : "Missing user"}), 404
    
    new_username = data.get("username")
    new_email = data.get("email")
    new_password = data.get("password")

    if new_username:
        user.username = new_username
    if new_email:
        user.email = new_email
    if new_password:
        user.password = bcrypt.generate_password_hash(new_password).decode('utf-8')

    db.session.commit()

    return jsonify({"message": f"User '{username}' was saved correctly"}), 200

@app.route("/users/<string:username>", methods=['DELETE'])
def delete_user(username):
    user = User.query.filter_by(username=username).first()

    if not user:
        return jsonify({"Error" : "User not found"}), 404
    
    db.session.delete(user)
    db.session.commit()

    return jsonify({"message": f"User '{username}' was deleted"}), 200

@app.route("/")
def login():
    auth_url = sp_oauth.get_authorize_url()
    return redirect(auth_url)

@app.route("/callback", methods=['GET'])
def callback():
    code = request.args.get('code')
    if not code:
        return redirect(sp_oauth.get_authorize_url())
    try:
        token_info = sp_oauth.get_access_token(code)
        access_token = token_info['access_token']
        refresh_token = token_info.get('refresh_token')

        sp = spotipy.Spotify(auth=access_token)
        user_data = sp.current_user()
        spotify_id = user_data['id']

        user = User.query.filter_by(spotify_id=spotify_id).first()
        if not user:
            new_user = User(spotify_id=spotify_id, access_token=access_token, refresh_token=refresh_token)
            db.session.add(new_user)
            db.session.commit()
        else:
            user.access_token = access_token
            user.refresh_token = refresh_token
            db.session.commit()
        
        session['token_info'] = token_info

    except Exception as e:
        return f"Error getting access token: {e}", 400 
    
    return redirect('/favorites')

@app.route("/users")
def users():
    users = User.query.all()
    user_list = [{"spotify_id": user.spotify_id, "access_token": user.access_token} for user in users]
    return jsonify(user_list)

@app.route("/favorites")
def favorites():
    token_info = session.get('token_info', None)
    if not token_info:
        return redirect('/')
    
    sp = spotipy.Spotify(auth=token_info['access_token'])
    
    try:

        token_info = session.get('token_info')
        access_token = token_info['access_token']
        sp = spotipy.Spotify(auth=access_token)
        user_data = sp.current_user()
        spotify_id = user_data['id']

        user = User.query.filter_by(spotify_id=spotify_id).first()
        if not user:
            return "User not found in the database.", 404
        
        top_artists = sp.current_user_top_artists(limit=10, time_range='medium_term')
        for artist in top_artists['items']:
            existing_artist = FavoriteArtist.query.filter_by(user_id=user.id, name=artist['name']).first()
            if not existing_artist:
                new_artist = FavoriteArtist(
                    user_id=user.id,
                    name=artist['name'],
                    genres=", ".join(artist['genres'])  
                )
                db.session.add(new_artist)
        
        db.session.commit()

        top_tracks = sp.current_user_top_tracks(limit=10, time_range='medium_term')
        for track in top_tracks['items']:
            existing_song = FavoriteSong.query.filter_by(user_id=user.id, title=track['name']).first()
            if not existing_song:
                new_song = FavoriteSong(
                    user_id=user.id,
                    title=track['name'],
                    artist=track['artists'][0]['name'],
                    album=track['album']['name'],
                    popularity=track['popularity']
                )
                db.session.add(new_song)
        
        db.session.commit()
        
        response_data = {
        "message": "Data successfully saved to the database.",
        "user": {
            "spotify_id": user.spotify_id, 
            "id": user.id 
            }
        }

        return jsonify(response_data), 200

    except Exception as e:
        return jsonify({"error": f"Error getting or saving data: {e}"}), 500

if __name__ == '__main__':
    app.run(debug=True)