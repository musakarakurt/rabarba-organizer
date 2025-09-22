import os
import re
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from flask import Flask, redirect, request, session, url_for, render_template, jsonify
import requests
from datetime import datetime
import time

# Debug: Environment variables kontrolü
print("=== RABARBA APP STARTING ===")
print("Environment Variables:")
print(f"RENDER: {os.getenv('RENDER')}")
print(f"SPOTIPY_CLIENT_ID: {'SET' if os.getenv('SPOTIPY_CLIENT_ID') else 'MISSING'}")
print(f"SPOTIPY_CLIENT_SECRET: {'SET' if os.getenv('SPOTIPY_CLIENT_SECRET') else 'MISSING'}")
print(f"SPOTIPY_REDIRECT_URI: {os.getenv('SPOTIPY_REDIRECT_URI')}")
print(f"FLASK_SECRET_KEY: {'SET' if os.getenv('FLASK_SECRET_KEY') else 'MISSING'}")
print("=============================")

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'rabarba_backup_secret_2024')

# Spotify API ayarları - DOĞRU İSİMLERLE
SPOTIFY_CLIENT_ID = os.getenv('SPOTIPY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIPY_CLIENT_SECRET')
SPOTIFY_REDIRECT_URI = os.getenv('SPOTIPY_REDIRECT_URI')

# Eğer Render'da çalışıyorsak redirect URI'yı güncelle
if os.getenv('RENDER'):
    hostname = os.getenv('RENDER_EXTERNAL_HOSTNAME', 'rabarba-organizer')
    # .onrender.com zaten hostname'de var, tekrar ekleme
    if not hostname.endswith('.onrender.com'):
        hostname = f"{hostname}.onrender.com"
    SPOTIFY_REDIRECT_URI = f"https://{hostname}/callback"
    print(f"Render mode detected. Redirect URI set to: {SPOTIFY_REDIRECT_URI}")

# Spotipy için environment variables set et
if SPOTIFY_CLIENT_ID:
    os.environ['SPOTIPY_CLIENT_ID'] = SPOTIFY_CLIENT_ID
if SPOTIFY_CLIENT_SECRET:
    os.environ['SPOTIPY_CLIENT_SECRET'] = SPOTIFY_CLIENT_SECRET
if SPOTIFY_REDIRECT_URI:
    os.environ['SPOTIPY_REDIRECT_URI'] = SPOTIFY_REDIRECT_URI

# Credential kontrolü
if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
    print("❌ ERROR: Spotify credentials missing!")
    if not SPOTIFY_CLIENT_ID:
        print("   - SPOTIPY_CLIENT_ID is missing")
    if not SPOTIFY_CLIENT_SECRET:
        print("   - SPOTIPY_CLIENT_SECRET is missing")
else:
    print("✅ Spotify credentials loaded successfully")

SCOPE = 'playlist-modify-public,playlist-modify-private,user-library-read'

# İstenen konuklar listesi
TARGET_GUESTS = [
    "Nuri Çetin", "Kemal Ayça", "İlker Gümüşoluk", "Anlatan Adam", 
    "Anlatanadam", "Alper Çelik", "Ömür Okumuş", "Erman Arıcasoy"
]

def get_spotify_client():
    """Spotify client'ını döndürür"""
    token_info = session.get('token_info')
    if not token_info:
        return None
    
    # Token süresi dolmuşsa yenile
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

def get_episode_details(episode):
    """Bölüm detaylarını çıkarır"""
    name = episode['name']
    release_date = episode['release_date']
    uri = episode['uri']
    description = episode.get('description', '')
    
    return {
        'name': name,
        'release_date': release_date,
        'uri': uri,
        'description': description,
        'episode_number': extract_episode_number(name),
        'part': extract_part(name),
        'id': episode['id']
    }

def extract_episode_number(name):
    """Bölüm numarasını çıkarır"""
    # 001, 0322, 1548 gibi formatları yakala
    match = re.search(r'(\d{3,4})', name)
    return int(match.group(1)) if match else 0

def extract_part(name):
    """Bölüm parçasını (A/B) çıkarır"""
    match = re.search(r'\s([AB])(?:\s|$|\))', name)
    return match.group(1) if match else None

def contains_target_guest(description, episode_number):
    """Açıklamada hedef konukların olup olmadığını kontrol eder"""
    # 322 A'dan önceki bölümler için filtreleme yapma
    if episode_number < 322:
        return True
    
    description_lower = description.lower()
    
    # Konuk isimlerini kontrol et
    for guest in TARGET_GUESTS:
        if guest.lower() in description_lower:
            return True
    
    return False

def sort_episodes(episodes):
    """Bölümleri doğru sıraya göre sıralar"""
    def episode_key(ep):
        num = ep['episode_number']
        part = ep['part']
        
        # Part sıralaması: None (tek bölüm) -> A -> B
        part_order = {'A': 1, 'B': 2}
        part_value = part_order.get(part, 0) if part else 0
        
        return (num, part_value)
    
    return sorted(episodes, key=episode_key)

@app.route('/')
def index():
    """Ana sayfa"""
    token_info = session.get('token_info')
    logged_in = token_info is not None
    
    # Debug info
    print(f"Homepage accessed. Logged in: {logged_in}")
    
    return render_template('index.html', logged_in=logged_in)

@app.route('/login')
def login():
    """Spotify girişi"""
    print("Login endpoint accessed")
    
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        error_msg = "Spotify credentials not configured. Please check environment variables."
        print(f"❌ {error_msg}")
        return jsonify({'error': error_msg}), 500
    
    try:
        sp_oauth = SpotifyOAuth(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET,
            redirect_uri=SPOTIFY_REDIRECT_URI,
            scope=SCOPE
        )
        auth_url = sp_oauth.get_authorize_url()
        print(f"Redirecting to Spotify auth: {auth_url}")
        return redirect(auth_url)
    except Exception as e:
        error_msg = f"Spotify OAuth error: {str(e)}"
        print(f"❌ {error_msg}")
        return jsonify({'error': error_msg}), 500

@app.route('/callback')
def callback():
    """Spotify callback"""
    print("Callback endpoint accessed")
    print(f"Request args: {dict(request.args)}")
    
    try:
        sp_oauth = SpotifyOAuth(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET,
            redirect_uri=SPOTIFY_REDIRECT_URI,
            scope=SCOPE
        )
        
        token_info = sp_oauth.get_access_token(request.args['code'])
        session['token_info'] = token_info
        print("✅ Authentication successful")
        return redirect(url_for('dashboard'))
    except Exception as e:
        error_msg = f"Authentication failed: {str(e)}"
        print(f"❌ {error_msg}")
        return error_msg

@app.route('/dashboard')
def dashboard():
    """Kontrol paneli"""
    print("Dashboard accessed")
    
    sp = get_spotify_client()
    if not sp:
        print("❌ Not authenticated, redirecting to login")
        return redirect(url_for('login'))
    
    try:
        user = sp.current_user()
        print(f"✅ User: {user['display_name']}")
        return render_template('dashboard.html', user=user)
    except Exception as e:
        print(f"❌ Dashboard error: {e}")
        session.clear()
        return redirect(url_for('login'))

@app.route('/load_episodes')
def load_episodes():
    """Tüm bölümleri yükle"""
    print("Load episodes endpoint accessed")
    
    sp = get_spotify_client()
    if not sp:
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        show_id = '40ORgVQqJWPQGRMUXmL67y'
        all_episodes = []
        
        print("Fetching episodes from Spotify...")
        
        # Tüm bölümleri getir
        results = sp.show_episodes(show_id, limit=50, offset=0)
        while results['items']:
            for episode in results['items']:
                episode_details = get_episode_details(episode)
                all_episodes.append(episode_details)
            
            if results['next']:
                results = sp.next(results)
            else:
                break
        
        print(f"Fetched {len(all_episodes)} episodes")
        
        # Bölümleri sırala
        sorted_episodes = sort_episodes(all_episodes)
        
        # Filtreleme yap
        chosen_episodes = []
        for ep in sorted_episodes:
            if contains_target_guest(ep['description'], ep['episode_number']):
                chosen_episodes.append(ep)
        
        session['all_episodes'] = sorted_episodes
        session['chosen_episodes'] = chosen_episodes
        session['unplayed_episodes'] = chosen_episodes.copy()
        
        print(f"✅ Episodes loaded: Total: {len(sorted_episodes)}, Chosen: {len(chosen_episodes)}")
        
        return jsonify({
            'total_episodes': len(sorted_episodes),
            'chosen_episodes': len(chosen_episodes),
            'unplayed_episodes': len(chosen_episodes)
        })
    
    except Exception as e:
        error_msg = f"Error loading episodes: {str(e)}"
        print(f"❌ {error_msg}")
        return jsonify({'error': error_msg}), 500

@app.route('/view_lists')
def view_lists():
    """Listeleri görüntüle"""
    all_episodes = session.get('all_episodes', [])
    chosen_episodes = session.get('chosen_episodes', [])
    unplayed_episodes = session.get('unplayed_episodes', [])
    
    print(f"View lists: All: {len(all_episodes)}, Chosen: {len(chosen_episodes)}, Unplayed: {len(unplayed_episodes)}")
    
    return render_template('view_lists.html',
                         all_episodes=all_episodes,
                         chosen_episodes=chosen_episodes,
                         unplayed_episodes=unplayed_episodes)

@app.route('/sync_playlists')
def sync_playlists():
    """Spotify listelerini senkronize et"""
    print("Sync playlists endpoint accessed")
    
    sp = get_spotify_client()
    if not sp:
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        user = sp.current_user()
        user_id = user['id']
        
        print(f"Syncing playlists for user: {user['display_name']}")
        
        # Playlist'leri oluştur veya bul
        chosen_playlist = create_or_find_playlist(sp, user_id, "Rabarba Choosen")
        unplayed_playlist = create_or_find_playlist(sp, user_id, "Rabarba Unplayed")
        
        # Bölüm URI'larını hazırla
        chosen_episodes = session.get('chosen_episodes', [])
        unplayed_episodes = session.get('unplayed_episodes', [])
        
        chosen_uris = [ep['uri'] for ep in chosen_episodes]
        unplayed_uris = [ep['uri'] for ep in unplayed_episodes]
        
        print(f"Syncing: Chosen: {len(chosen_uris)} episodes, Unplayed: {len(unplayed_uris)} episodes")
        
        # Playlist'leri güncelle
        update_playlist(sp, chosen_playlist['id'], chosen_uris)
        update_playlist(sp, unplayed_playlist['id'], unplayed_uris)
        
        print("✅ Playlists synced successfully")
        
        return jsonify({
            'success': True,
            'chosen_playlist': chosen_playlist['external_urls']['spotify'],
            'unplayed_playlist': unplayed_playlist['external_urls']['spotify'],
            'message': f'Playlistler güncellendi! Seçilen: {len(chosen_episodes)} bölüm, Oynatılmayan: {len(unplayed_episodes)} bölüm'
        })
    
    except Exception as e:
        error_msg = f"Error syncing playlists: {str(e)}"
        print(f"❌ {error_msg}")
        return jsonify({'error': error_msg}), 500

def create_or_find_playlist(sp, user_id, playlist_name):
    """Playlist oluştur veya bul"""
    playlists = sp.current_user_playlists(limit=50)
    
    for playlist in playlists['items']:
        if playlist['name'] == playlist_name:
            print(f"Found existing playlist: {playlist_name}")
            return playlist
    
    # Yeni playlist oluştur
    print(f"Creating new playlist: {playlist_name}")
    new_playlist = sp.user_playlist_create(
        user_id, 
        playlist_name,
        public=False,
        description=f"Rabarba podcast bölümleri - {datetime.now().strftime('%Y-%m-%d')}"
    )
    
    return new_playlist

def update_playlist(sp, playlist_id, episode_uris):
    """Playlist'i güncelle"""
    # Önce mevcut bölümleri temizle
    sp.playlist_replace_items(playlist_id, [])
    
    if not episode_uris:
        print("No episodes to add to playlist")
        return
    
    # Yeni bölümleri ekle (Spotify API 100 item limiti var)
    for i in range(0, len(episode_uris), 100):
        batch = episode_uris[i:i + 100]
        sp.playlist_add_items(playlist_id, batch)
    
    print(f"Added {len(episode_uris)} episodes to playlist")

@app.route('/mark_played/<int:episode_number>')
def mark_played(episode_number):
    """Bölümü oynatılmış olarak işaretle"""
    try:
        unplayed_episodes = session.get('unplayed_episodes', [])
        
        # Bölümü unplayed listesinden kaldır
        new_unplayed = [ep for ep in unplayed_episodes if ep['episode_number'] != episode_number]
        session['unplayed_episodes'] = new_unplayed
        
        print(f"Marked episode {episode_number} as played. Remaining: {len(new_unplayed)}")
        
        return jsonify({'success': True, 'remaining': len(new_unplayed)})
    
    except Exception as e:
        error_msg = f"Error marking episode as played: {str(e)}"
        print(f"❌ {error_msg}")
        return jsonify({'error': error_msg}), 500

@app.route('/get_stats')
def get_stats():
    """İstatistikleri getir"""
    all_episodes = session.get('all_episodes', [])
    chosen_episodes = session.get('chosen_episodes', [])
    unplayed_episodes = session.get('unplayed_episodes', [])
    
    return jsonify({
        'total_episodes': len(all_episodes),
        'chosen_episodes': len(chosen_episodes),
        'unplayed_episodes': len(unplayed_episodes)
    })

@app.route('/logout')
def logout():
    """Çıkış yap"""
    print("User logged out")
    session.clear()
    return redirect(url_for('index'))

@app.errorhandler(404)
def not_found(error):
    return render_template('index.html'), 404

@app.errorhandler(500)
def internal_error(error):
    print(f"500 Error: {error}")
    return jsonify({'error': 'Internal server error'}), 500

# Health check endpoint for Render
@app.route('/health')
def health_check():
    return jsonify({
        'status': 'healthy', 
        'timestamp': datetime.now().isoformat(),
        'spotify_configured': bool(SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET)
    })

@app.route('/debug')
def debug():
    """Debug endpoint"""
    debug_info = {
        'environment_variables': {
            'RENDER': os.getenv('RENDER'),
            'SPOTIPY_CLIENT_ID_SET': bool(os.getenv('SPOTIPY_CLIENT_ID')),
            'SPOTIPY_CLIENT_SECRET_SET': bool(os.getenv('SPOTIPY_CLIENT_SECRET')),
            'SPOTIPY_REDIRECT_URI': os.getenv('SPOTIPY_REDIRECT_URI'),
            'FLASK_SECRET_KEY_SET': bool(os.getenv('FLASK_SECRET_KEY'))
        },
        'app_variables': {
            'SPOTIFY_CLIENT_ID': SPOTIFY_CLIENT_ID,
            'SPOTIFY_CLIENT_SECRET': '***' if SPOTIFY_CLIENT_SECRET else None,
            'SPOTIFY_REDIRECT_URI': SPOTIFY_REDIRECT_URI
        },
        'session': {
            'has_token': 'token_info' in session,
            'episodes_loaded': len(session.get('all_episodes', []))
        }
    }
    return jsonify(debug_info)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('DEBUG', 'False').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug_mode)