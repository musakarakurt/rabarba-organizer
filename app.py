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
app.config['JSONIFY_PRETTYPRINT_REGULAR'] = False  # JSON response'ları küçült

# Spotify API ayarları - DOĞRU İSİMLERLE
SPOTIFY_CLIENT_ID = os.getenv('SPOTIPY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIPY_CLIENT_SECRET')
SPOTIFY_REDIRECT_URI = os.getenv('SPOTIPY_REDIRECT_URI')

# Eğer Render'da çalışıyorsak redirect URI'yı güncelle
if os.getenv('RENDER'):
    hostname = os.getenv('RENDER_EXTERNAL_HOSTNAME', 'rabarba-organizer')
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
    if not episode:
        return None
        
    return {
        'name': episode.get('name', ''),
        'release_date': episode.get('release_date', ''),
        'uri': episode.get('uri', ''),
        'description': episode.get('description', ''),
        'episode_number': extract_episode_number(episode.get('name', '')),
        'part': extract_part(episode.get('name', '')),
        'id': episode.get('id', '')
    }

def extract_episode_number(name):
    """Bölüm numarasını çıkarır"""
    match = re.search(r'(\d{3,4})', name)
    return int(match.group(1)) if match else 0

def extract_part(name):
    """Bölüm parçasını (A/B) çıkarır"""
    match = re.search(r'\s([AB])(?:\s|$|\))', name)
    return match.group(1) if match else None

def contains_target_guest(description, episode_number):
    """Açıklamada hedef konukların olup olmadığını kontrol eder"""
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
    """Bölümleri doğru sıraya göre sıralar"""
    def episode_key(ep):
        num = ep['episode_number']
        part = ep['part']
        part_order = {'A': 1, 'B': 2}
        part_value = part_order.get(part, 0) if part else 0
        return (num, part_value)
    
    return sorted(episodes, key=episode_key)

@app.route('/')
def index():
    """Ana sayfa"""
    token_info = session.get('token_info')
    logged_in = token_info is not None
    return render_template('index.html', logged_in=logged_in)

@app.route('/login')
def login():
    """Spotify girişi"""
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
    """Spotify callback"""
    try:
        sp_oauth = SpotifyOAuth(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET,
            redirect_uri=SPOTIFY_REDIRECT_URI,
            scope=SCOPE
        )
        token_info = sp_oauth.get_access_token(request.args['code'])
        session['token_info'] = token_info
        return redirect(url_for('dashboard'))
    except Exception as e:
        return f"Authentication failed: {str(e)}"

@app.route('/dashboard')
def dashboard():
    """Kontrol paneli"""
    sp = get_spotify_client()
    if not sp:
        return redirect(url_for('login'))
    
    try:
        user = sp.current_user()
        return render_template('dashboard.html', user=user)
    except Exception as e:
        session.clear()
        return redirect(url_for('login'))

@app.route('/load_episodes')
def load_episodes():
    """Tüm bölümleri yükle - OPTIMIZE EDILMIS"""
    sp = get_spotify_client()
    if not sp:
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        show_id = '40ORgVQqJWPQGRMUXmL67y'
        all_episodes = []
        
        # Bölümleri sayfalı olarak getir
        results = sp.show_episodes(show_id, limit=50, offset=0)
        
        if not results or 'items' not in results:
            return jsonify({'error': 'No episodes found'}), 500
        
        page_count = 0
        while results and results.get('items'):
            page_count += 1
            for episode in results['items']:
                if episode:
                    episode_details = get_episode_details(episode)
                    if episode_details:
                        all_episodes.append(episode_details)
            
            # Sadece ilk 10 sayfa yükle (500 bölüm) - timeout'u önle
            if page_count >= 10 or not results.get('next'):
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
            if contains_target_guest(ep['description'], ep['episode_number']):
                chosen_episodes.append(ep)
        
        # Session'a kaydet (sadece ID'leri sakla - hafıza için)
        session['all_episodes'] = sorted_episodes
        session['chosen_episodes'] = chosen_episodes
        session['unplayed_episodes'] = chosen_episodes.copy()
        
        return jsonify({
            'success': True,
            'total_episodes': len(sorted_episodes),
            'chosen_episodes': len(chosen_episodes),
            'unplayed_episodes': len(chosen_episodes),
            'message': f'{len(sorted_episodes)} bölüm yüklendi ({len(chosen_episodes)} seçilen)'
        })
    
    except Exception as e:
        return jsonify({'error': f'Error loading episodes: {str(e)}'}), 500

@app.route('/view_lists')
def view_lists():
    """Listeleri görüntüle - OPTIMIZE EDILMIS"""
    # Sadece ilk 100 bölümü göster - performance için
    all_episodes = session.get('all_episodes', [])[:100]
    chosen_episodes = session.get('chosen_episodes', [])[:100]
    unplayed_episodes = session.get('unplayed_episodes', [])[:100]
    
    return render_template('view_lists.html',
                         all_episodes=all_episodes,
                         chosen_episodes=chosen_episodes,
                         unplayed_episodes=unplayed_episodes)

@app.route('/sync_playlists')
def sync_playlists():
    """Spotify listelerini senkronize et"""
    sp = get_spotify_client()
    if not sp:
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        user = sp.current_user()
        user_id = user['id']
        
        # Playlist'leri oluştur veya bul
        chosen_playlist = create_or_find_playlist(sp, user_id, "Rabarba Choosen")
        unplayed_playlist = create_or_find_playlist(sp, user_id, "Rabarba Unplayed")
        
        # Bölüm URI'larını hazırla
        chosen_episodes = session.get('chosen_episodes', [])
        unplayed_episodes = session.get('unplayed_episodes', [])
        
        chosen_uris = [ep['uri'] for ep in chosen_episodes if ep.get('uri')]
        unplayed_uris = [ep['uri'] for ep in unplayed_episodes if ep.get('uri')]
        
        # Playlist'leri güncelle
        update_playlist(sp, chosen_playlist['id'], chosen_uris)
        update_playlist(sp, unplayed_playlist['id'], unplayed_uris)
        
        return jsonify({
            'success': True,
            'chosen_playlist': chosen_playlist['external_urls']['spotify'],
            'unplayed_playlist': unplayed_playlist['external_urls']['spotify'],
            'message': f'Playlistler güncellendi! Seçilen: {len(chosen_episodes)} bölüm'
        })
    
    except Exception as e:
        return jsonify({'error': f'Error syncing playlists: {str(e)}'}), 500

def create_or_find_playlist(sp, user_id, playlist_name):
    """Playlist oluştur veya bul"""
    playlists = sp.current_user_playlists(limit=50)
    for playlist in playlists['items']:
        if playlist['name'] == playlist_name:
            return playlist
    
    new_playlist = sp.user_playlist_create(
        user_id, 
        playlist_name,
        public=False,
        description=f"Rabarba podcast bölümleri - {datetime.now().strftime('%Y-%m-%d')}"
    )
    return new_playlist

def update_playlist(sp, playlist_id, episode_uris):
    """Playlist'i güncelle"""
    if not episode_uris:
        return
        
    sp.playlist_replace_items(playlist_id, [])
    for i in range(0, len(episode_uris), 100):
        batch = episode_uris[i:i + 100]
        sp.playlist_add_items(playlist_id, batch)

@app.route('/mark_played/<int:episode_number>')
def mark_played(episode_number):
    """Bölümü oynatılmış olarak işaretle"""
    try:
        unplayed_episodes = session.get('unplayed_episodes', [])
        session['unplayed_episodes'] = [ep for ep in unplayed_episodes if ep['episode_number'] != episode_number]
        return jsonify({'success': True, 'remaining': len(session['unplayed_episodes'])})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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
    session.clear()
    return redirect(url_for('index'))

@app.route('/health')
def health_check():
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

@app.route('/debug')
def debug():
    return jsonify({
        'session_keys': list(session.keys()),
        'episode_counts': {
            'all': len(session.get('all_episodes', [])),
            'chosen': len(session.get('chosen_episodes', [])),
            'unplayed': len(session.get('unplayed_episodes', []))
        }
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)