from flask import Flask, jsonify, request, redirect, session, url_for, render_template
from flask_cors import CORS
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import os
import requests
from dotenv import load_dotenv
from yt_dlp import YoutubeDL

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "supersecretkey")
CORS(app, supports_credentials=True)

load_dotenv()

SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
SPOTIPY_REDIRECT_URI = os.getenv("SPOTIPY_REDIRECT_URI")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

SCOPE = "user-library-read"

def create_spotify_oauth(cache_path=None):
    return SpotifyOAuth(
        client_id=SPOTIPY_CLIENT_ID,
        client_secret=SPOTIPY_CLIENT_SECRET,
        redirect_uri=SPOTIPY_REDIRECT_URI,
        scope=SCOPE,
        cache_path=cache_path,
        show_dialog=True
    )

def get_spotify_client():
    user_id = session.get("user_id")
    if not user_id:
        return None
    cache_path = f".cache-{user_id}"
    sp_oauth = create_spotify_oauth(cache_path=cache_path)
    token_info = sp_oauth.get_cached_token()
    if not token_info:
        return None
    if sp_oauth.is_token_expired(token_info):
        token_info = sp_oauth.refresh_access_token(token_info['refresh_token'])
        sp_oauth.cache_handler.save_token_to_cache(token_info)
    return spotipy.Spotify(auth=token_info['access_token'])

@app.route('/')
def login():
    redirect_type = request.args.get('redirect', 'web')
    session['post_auth_redirect'] = redirect_type
    sp_oauth = create_spotify_oauth()
    auth_url = sp_oauth.get_authorize_url()
    return redirect(auth_url)

@app.route('/callback')
def callback():
    sp_oauth = create_spotify_oauth()
    code = request.args.get('code')
    if not code:
        if not code:
            redirect_type = session.pop('post_auth_redirect', 'web')
            if redirect_type == 'app':
                return redirect('spotify1://callback?error=cancelled')
            else:
                return "Error: no code provided", 400
    token_info = sp_oauth.get_access_token(code, as_dict=True)
    sp = spotipy.Spotify(auth=token_info['access_token'])
    user = sp.current_user()
    session["user_id"] = user['id']
    cache_path = f".cache-{user['id']}"
    sp_oauth.cache_handler.cache_path = cache_path
    sp_oauth.cache_handler.save_token_to_cache(token_info)

    # Decide where to redirect after auth
    redirect_type = session.pop('post_auth_redirect', 'web')
    if redirect_type == 'app':
        # Pass the access token to the app via deep link
        return redirect(f'spotify1://callback?access_token={token_info["access_token"]}')
    else:
        return redirect('/player')

@app.route('/player')
def player():
    return render_template('player.html')

@app.route('/liked')
def liked_tracks():
    # Try to get access token from Authorization header (for app)
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        token = auth_header.split(' ', 1)[1]
        sp = spotipy.Spotify(auth=token)
    else:
        # Fallback to session-based (for web)
        sp = get_spotify_client()
        if not sp:
            return redirect('/')

    tracks = []
    results = sp.current_user_saved_tracks(limit=50)

    while results:
        for item in results['items']:
            track = item['track']
            tracks.append({
                'id': track['id'],
                'name': track['name'],
                'artist': track['artists'][0]['name'],
                'album': track['album']['name'],
                'album_art': track['album']['images'][0]['url'] if track['album']['images'] else ''
            })
        if results['next']:
            results = sp.next(results)
        else:
            results = None

    return jsonify(tracks)

@app.route('/youtube_search')
def youtube_search():
    query = request.args.get('q')
    if not query:
        return jsonify({'error': 'Missing query parameter'}), 400
    url = ("https://www.googleapis.com/youtube/v3/search"
           "?part=snippet&type=video&maxResults=1&key=" + YOUTUBE_API_KEY +
           "&q=" + query)
    resp = requests.get(url)
    data = resp.json()
    if "items" in data and len(data["items"]) > 0:
        video_id = data["items"][0]["id"]["videoId"]
        return jsonify({"videoId": video_id})
    return jsonify({"videoId": None})

@app.route('/youtube_search_multiple')
def youtube_search_multiple():
    query = request.args.get('q')
    url = (
        "https://www.googleapis.com/youtube/v3/search"
        "?part=snippet&type=video&maxResults=5&key=" + YOUTUBE_API_KEY +
        "&q=" + query
    )
    r = requests.get(url)
    data = r.json()
    results = []
    for item in data.get('items', []):
        results.append({
            'videoId': item['id']['videoId'],
            'title': item['snippet']['title'],
            'channelTitle': item['snippet']['channelTitle'],
            'thumbnail': item['snippet']['thumbnails']['default']['url']
        })
    return jsonify(results)

@app.route('/youtube_audio')
def youtube_audio():
    video_id = request.args.get('videoId')
    if not video_id:
        return jsonify({"error": "Missing videoId"}), 400

    url = f"https://www.youtube.com/watch?v={video_id}"

    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'noplaylist': True,
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            audio_url = info['url']
            return jsonify({"audio_url": audio_url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    print("YOUTUBE_API_KEY =", YOUTUBE_API_KEY)
    print("SPOTIPY_CLIENT_ID =", SPOTIPY_CLIENT_ID)
    app.run(host='0.0.0.0', port=8888)