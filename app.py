import os
import re
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from flask import Flask, redirect, request, session, url_for, render_template, jsonify
import requests
from datetime import datetime
import time
import json

print("=== RABARBA APP STARTING ===")

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'rabarba_backup_secret_2024')
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Spotify API ayarları
SPOTIFY_CLIENT_ID = os.getenv('SPOTIPY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIPY_CLIENT_SECRET')
SPOTIFY_REDIRECT_URI = os.getenv('SPOTIPY_REDIRECT_URI')

if os.getenv('RENDER'):
    hostname = os.getenv('RENDER_EXTERNAL_HOSTNAME', 'rabarba-organizer')
    if not hostname.endswith('.onrender.com'):
        hostname = f"{hostname}.onrender.com"
    SPOTIFY_REDIRECT_URI = f"https://{hostname}/callback"

# Spotipy için environment variables set et
if SPOTIFY_CLIENT_ID:
    os.environ['SPOTIPY_CLIENT_ID'] = SPOTIFY_CLIENT_ID
if SPOTIFY_CLIENT_SECRET:
    os.environ['SPOTIPY_CLIENT_SECRET'] = SPOTIFY_CLIENT_SECRET
if SPOTIFY_REDIRECT_URI:
    os.environ['SPOTIPY_REDIRECT_URI'] = SPOTIFY_REDIRECT_URI

SCOPE = 'playlist-modify-public,playlist-modify-private,user-library-read'

TARGET_GUESTS = [
    "Nuri Çetin", "Kemal Ayça", "İlker Gümüşoluk", "Anlatan Adam", 
    "Anlatanadam", "Alper Çelik", "Ömür Okumuş", "Erman Arıcasoy"
]

# Basit veritabanı (session yerine)
user_data = {}

def get_spotify_client():
    """Spotify client'ını döndürür"""
    token_info = session.get('token_info')
    if not token_info:
        return None
    
    if token_info['expires_at'] < time.time():
        try:
            sp_oauth = SpotifyOAuth(
                client_id=SPOTIFY_CLIENT_ID,
                client_secret=SPOTIFY_CLIENT_SECRET,
                redirect_uri=SPOTIFY_REDIRECT_URI,
                scope=SCOPE
            )
            token_info = sp_oauth.refresh_access_token(token_info['refresh_token'])
            session['token_info'] = token_info
        except Exception as e:
            print(f"Token refresh error: {e}")
            return None
    
    return spotipy.Spotify(auth=token_info['access_token'])

def get_user_id():
    """Kullanıcı ID'sini al"""
    sp = get_spotify_client()
    if not sp:
        return None
    try:
        user = sp.current_user()
        return user['id']
    except:
        return None

def get_episode_details(episode):
    """Bölüm detaylarını çıkarır - MINIMAL"""
    if not episode:
        return None
        
    return {
        'name': episode.get('name', ''),
        'uri': episode.get('uri', ''),
        'episode_number': extract_episode_number(episode.get('name', '')),
        'part': extract_part(episode.get('name', ''))
    }

def extract_episode_number(name):
    match = re.search(r'(\d{3,4})', name)
    return int(match.group(1)) if match else 0

def extract_part(name):
    match = re.search(r'\s([AB])(?:\s|$|\))', name)
    return match.group(1) if match else None

def contains_target_guest(description, episode_number):
    if episode_number < 322:
        return True
    if not description:
        return False
    description_lower = description.lower()
    for guest in TARGET_GUESTS:
        if guest.lower() in description_lower:
            return True
    return False

def sort_episodes(episodes):
    def episode_key(ep):
        num = ep['episode_number']
        part = ep['part']
        part_order = {'A': 1, 'B': 2}
        part_value = part_order.get(part, 0) if part else 0
        return (num, part_value)
    return sorted(episodes, key=episode_key)

@app.route('/')
def index():
    token_info = session.get('token_info')
    logged_in = token_info is not None
    return render_template('index.html', logged_in=logged_in)

@app.route('/login')
def login():
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        return jsonify({'error': 'Spotify credentials not configured'}), 500
    
    try:
        sp_oauth = SpotifyOAuth(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET,
            redirect_uri=SPOTIFY_REDIRECT_URI,
            scope=SCOPE
        )
        auth_url = sp_oauth.get_authorize_url()
        return redirect(auth_url)
    except Exception as e:
        return jsonify({'error': f'Spotify OAuth error: {str(e)}'}), 500

@app.route('/callback')
def callback():
    try:
        sp_oauth = SpotifyOAuth(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET,
            redirect_uri=SPOTIFY_REDIRECT_URI,
            scope=SCOPE
        )
        token_info = sp_oauth.get_access_token(request.args['code'])
        
        # SADECE token_info'yu session'a kaydet
        session.clear()
        session['token_info'] = {
            'access_token': token_info['access_token'],
            'refresh_token': token_info['refresh_token'],
            'expires_at': token_info['expires_at']
        }
        
        return redirect(url_for('dashboard'))
    except Exception as e:
        return f"Authentication failed: {str(e)}"

@app.route('/dashboard')
def dashboard():
    sp = get_spotify_client()
    if not sp:
        return redirect(url_for('login'))
    
    try:
        user = sp.current_user()
        
        # Kullanıcı verilerini yükle
        user_id = user['id']
        user_episode_data = user_data.get(user_id, {})
        
        return render_template('dashboard.html', 
                             user=user,
                             episode_counts=user_episode_data.get('counts', {}))
    except Exception as e:
        session.clear()
        return redirect(url_for('login'))

@app.route('/load_episodes')
def load_episodes():
    sp = get_spotify_client()
    if not sp:
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        user_id = get_user_id()
        if not user_id:
            return jsonify({'error': 'User not found'}), 401
        
        show_id = '40ORgVQqJWPQGRMUXmL67y'
        all_episodes = []
        
        # Sadece 2 sayfa yükle (100 bölüm)
        results = sp.show_episodes(show_id, limit=50, offset=0)
        
        if not results or 'items' not in results:
            return jsonify({'error': 'No episodes found'}), 500
        
        page_count = 0
        while results and results.get('items') and page_count < 2:
            page_count += 1
            for episode in results['items']:
                if episode:
                    episode_details = get_episode_details(episode)
                    if episode_details:
                        all_episodes.append(episode_details)
            
            if page_count >= 2 or not results.get('next'):
                break
            try:
                results = sp.next(results)
            except:
                break
        
        if not all_episodes:
            return jsonify({'error': 'No episodes loaded'}), 500
        
        # Bölümleri sırala
        sorted_episodes = sort_episodes(all_episodes)
        
        # Filtreleme yap
        chosen_episodes = []
        for ep in sorted_episodes:
            if contains_target_guest('', ep['episode_number']):  # 322'den öncekileri al
                chosen_episodes.append(ep)
        
        # Verileri kaydet (session yerine memory'de)
        user_data[user_id] = {
            'all_episodes': sorted_episodes,
            'chosen_episodes': chosen_episodes,
            'unplayed_episodes': chosen_episodes.copy(),
            'counts': {
                'total': len(sorted_episodes),
                'chosen': len(chosen_episodes),
                'unplayed': len(chosen_episodes)
            },
            'timestamp': time.time()
        }
        
        return jsonify({
            'success': True,
            'total_episodes': len(sorted_episodes),
            'chosen_episodes': len(chosen_episodes),
            'unplayed_episodes': len(chosen_episodes),
            'message': f'{len(sorted_episodes)} bölüm yüklendi'
        })
    
    except Exception as e:
        return jsonify({'error': f'Error: {str(e)}'}), 500

@app.route('/view_lists')
def view_lists():
    user_id = get_user_id()
    if not user_id:
        return redirect(url_for('login'))
    
    episode_data = user_data.get(user_id, {})
    
    if not episode_data:
        return render_template('view_lists.html',
                             all_episodes=[],
                             chosen_episodes=[],
                             unplayed_episodes=[],
                             message="Henüz bölüm yüklenmedi")
    
    # Sadece ilk 30 bölümü göster
    all_episodes = episode_data.get('all_episodes', [])[:30]
    chosen_episodes = episode_data.get('chosen_episodes', [])[:30]
    unplayed_episodes = episode_data.get('unplayed_episodes', [])[:30]
    
    return render_template('view_lists.html',
                         all_episodes=all_episodes,
                         chosen_episodes=chosen_episodes,
                         unplayed_episodes=unplayed_episodes,
                         total_count=episode_data['counts']['total'],
                         chosen_count=episode_data['counts']['chosen'])

@app.route('/sync_playlists')
def sync_playlists():
    sp = get_spotify_client()
    if not sp:
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        user_id = get_user_id()
        if not user_id:
            return jsonify({'error': 'User not found'}), 401
        
        episode_data = user_data.get(user_id, {})
        if not episode_data:
            return jsonify({'error': 'Önce bölümleri yükleyin'}), 400
        
        # Playlist'leri oluştur
        chosen_playlist = create_or_find_playlist(sp, user_id, "Rabarba Choosen")
        unplayed_playlist = create_or_find_playlist(sp, user_id, "Rabarba Unplayed")
        
        # Bölüm URI'larını hazırla
        chosen_episodes = episode_data.get('chosen_episodes', [])
        unplayed_episodes = episode_data.get('unplayed_episodes', [])
        
        chosen_uris = [ep['uri'] for ep in chosen_episodes if ep.get('uri')]
        unplayed_uris = [ep['uri'] for ep in unplayed_episodes if ep.get('uri')]
        
        # Playlist'leri güncelle
        update_playlist(sp, chosen_playlist['id'], chosen_uris)
        update_playlist(sp, unplayed_playlist['id'], unplayed_uris)
        
        return jsonify({
            'success': True,
            'chosen_playlist': chosen_playlist['external_urls']['spotify'],
            'unplayed_playlist': unplayed_playlist['external_urls']['spotify'],
            'message': f'Playlistler oluşturuldu! {len(chosen_episodes)} bölüm'
        })
    
    except Exception as e:
        return jsonify({'error': f'Error: {str(e)}'}), 500

def create_or_find_playlist(sp, user_id, playlist_name):
    playlists = sp.current_user_playlists(limit=50)
    for playlist in playlists['items']:
        if playlist['name'] == playlist_name:
            return playlist
    
    new_playlist = sp.user_playlist_create(
        user_id, 
        playlist_name,
        public=False,
        description=f"Rabarba podcast - {datetime.now().strftime('%Y-%m-%d')}"
    )
    return new_playlist

def update_playlist(sp, playlist_id, episode_uris):
    if not episode_uris:
        return
    sp.playlist_replace_items(playlist_id, [])
    sp.playlist_add_items(playlist_id, episode_uris)

@app.route('/get_stats')
def get_stats():
    user_id = get_user_id()
    if not user_id:
        return jsonify({'error': 'Not authenticated'}), 401
    
    episode_data = user_data.get(user_id, {})
    counts = episode_data.get('counts', {'total': 0, 'chosen': 0, 'unplayed': 0})
    
    return jsonify({
        'total_episodes': counts['total'],
        'chosen_episodes': counts['chosen'],
        'unplayed_episodes': counts['unplayed']
    })

@app.route('/logout')
def logout():
    user_id = get_user_id()
    if user_id and user_id in user_data:
        del user_data[user_id]
    session.clear()
    return redirect(url_for('index'))

@app.route('/test_simple')
def test_simple():
    return jsonify({'status': 'ok', 'message': 'Server çalışıyor'})

@app.route('/test_session')
def test_session():
    return jsonify({
        'session_size': len(str(session)),
        'user_data_size': len(user_data)
    })

@app.route('/test_spotify')
def test_spotify():
    sp = get_spotify_client()
    if not sp:
        return jsonify({'error': 'Spotify bağlı değil'})
    
    try:
        results = sp.show_episodes('40ORgVQqJWPQGRMUXmL67y', limit=3, offset=0)
        return jsonify({
            'success': True,
            'episodes': len(results['items'])
        })
    except Exception as e:
        return jsonify({'error': str(e)})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)