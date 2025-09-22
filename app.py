import os
import re
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from flask import Flask, redirect, request, session, url_for, render_template, jsonify
import requests
from datetime import datetime
import time
import json

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
app.config['SESSION_COOKIE_MAX_SIZE'] = 4096  # 4KB limit
app.config['JSONIFY_PRETTYPRINT_REGULAR'] = False

# Spotify API ayarları
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

if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
    print("❌ ERROR: Spotify credentials missing!")
else:
    print("✅ Spotify credentials loaded successfully")

SCOPE = 'playlist-modify-public,playlist-modify-private,user-library-read'

TARGET_GUESTS = [
    "Nuri Çetin", "Kemal Ayça", "İlker Gümüşoluk", "Anlatan Adam", 
    "Anlatanadam", "Alper Çelik", "Ömür Okumuş", "Erman Arıcasoy"
]

# Basit veritabanı (dosya tabanlı)
DATA_FILE = 'episode_data.json'

def save_episode_data(user_id, data):
    """Episode verilerini dosyaya kaydet"""
    try:
        if os.getenv('RENDER'):
            # Render'da dosya sistemi geçici, session'da tut
            session['episode_data'] = data
            return
        
        if not os.path.exists(DATA_FILE):
            all_data = {}
        else:
            try:
                with open(DATA_FILE, 'r') as f:
                    all_data = json.load(f)
            except:
                all_data = {}
        
        all_data[user_id] = data
        
        with open(DATA_FILE, 'w') as f:
            json.dump(all_data, f)
    except Exception as e:
        print(f"Save data error: {e}")
        session['episode_data'] = data

def load_episode_data(user_id):
    """Episode verilerini dosyadan yükle"""
    try:
        if os.getenv('RENDER'):
            return session.get('episode_data', {})
        
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                all_data = json.load(f)
                return all_data.get(user_id, {})
        return {}
    except Exception as e:
        print(f"Load data error: {e}")
        return session.get('episode_data', {})

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
    """Bölüm detaylarını çıkarır - SADECE GEREKLİ BİLGİLER"""
    if not episode:
        return None
        
    return {
        'name': episode.get('name', ''),
        'release_date': episode.get('release_date', ''),
        'uri': episode.get('uri', ''),
        'description': episode.get('description', ''),
        'episode_number': extract_episode_number(episode.get('name', '')),
        'part': extract_part(episode.get('name', ''))
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
        user = sp.current_user()
        user_id = user['id']
        
        show_id = '40ORgVQqJWPQGRMUXmL67y'
        all_episodes = []
        
        # Bölümleri sayfalı olarak getir - LIMITLI
        results = sp.show_episodes(show_id, limit=50, offset=0)
        
        if not results or 'items' not in results:
            return jsonify({'error': 'No episodes found'}), 500
        
        page_count = 0
        max_pages = 5  # Sadece 250 bölüm (5 sayfa × 50 bölüm)
        
        while results and results.get('items') and page_count < max_pages:
            page_count += 1
            for episode in results['items']:
                if episode:
                    episode_details = get_episode_details(episode)
                    if episode_details:
                        all_episodes.append(episode_details)
            
            if page_count >= max_pages or not results.get('next'):
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
        
        # Verileri kaydet (session yerine dosyaya)
        episode_data = {
            'all_episodes': sorted_episodes,
            'chosen_episodes': chosen_episodes,
            'unplayed_episodes': chosen_episodes.copy(),
            'timestamp': datetime.now().isoformat()
        }
        
        save_episode_data(user_id, episode_data)
        
        # Session'a sadece sayıları kaydet
        session['episode_counts'] = {
            'total': len(sorted_episodes),
            'chosen': len(chosen_episodes),
            'unplayed': len(chosen_episodes)
        }
        
        return jsonify({
            'success': True,
            'total_episodes': len(sorted_episodes),
            'chosen_episodes': len(chosen_episodes),
            'unplayed_episodes': len(chosen_episodes),
            'message': f'Son {len(sorted_episodes)} bölüm yüklendi ({len(chosen_episodes)} seçilen)'
        })
    
    except Exception as e:
        return jsonify({'error': f'Error loading episodes: {str(e)}'}), 500

@app.route('/view_lists')
def view_lists():
    """Listeleri görüntüle - OPTIMIZE EDILMIS"""
    sp = get_spotify_client()
    if not sp:
        return redirect(url_for('login'))
    
    try:
        user = sp.current_user()
        user_id = user['id']
        
        # Verileri yükle
        episode_data = load_episode_data(user_id)
        
        if not episode_data:
            return render_template('view_lists.html',
                                 all_episodes=[],
                                 chosen_episodes=[],
                                 unplayed_episodes=[],
                                 message="Henüz bölüm yüklenmedi. Lütfen önce 'Bölümleri Yükle' butonuna tıklayın.")
        
        # Sadece ilk 50 bölümü göster
        all_episodes = episode_data.get('all_episodes', [])[:50]
        chosen_episodes = episode_data.get('chosen_episodes', [])[:50]
        unplayed_episodes = episode_data.get('unplayed_episodes', [])[:50]
        
        return render_template('view_lists.html',
                             all_episodes=all_episodes,
                             chosen_episodes=chosen_episodes,
                             unplayed_episodes=unplayed_episodes,
                             total_count=len(episode_data.get('all_episodes', [])),
                             chosen_count=len(episode_data.get('chosen_episodes', [])))
    
    except Exception as e:
        return jsonify({'error': f'Error loading lists: {str(e)}'}), 500

@app.route('/sync_playlists')
def sync_playlists():
    """Spotify listelerini senkronize et"""
    sp = get_spotify_client()
    if not sp:
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        user = sp.current_user()
        user_id = user['id']
        
        # Verileri yükle
        episode_data = load_episode_data(user_id)
        
        if not episode_data:
            return jsonify({'error': 'Önce bölümleri yükleyin'}), 400
        
        # Playlist'leri oluştur veya bul
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
        sp = get_spotify_client()
        if not sp:
            return jsonify({'error': 'Not authenticated'}), 401
        
        user = sp.current_user()
        user_id = user['id']
        
        episode_data = load_episode_data(user_id)
        if not episode_data:
            return jsonify({'error': 'No episode data'}), 400
        
        unplayed_episodes = episode_data.get('unplayed_episodes', [])
        new_unplayed = [ep for ep in unplayed_episodes if ep['episode_number'] != episode_number]
        episode_data['unplayed_episodes'] = new_unplayed
        
        save_episode_data(user_id, episode_data)
        
        return jsonify({'success': True, 'remaining': len(new_unplayed)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/get_stats')
def get_stats():
    """İstatistikleri getir"""
    counts = session.get('episode_counts', {'total': 0, 'chosen': 0, 'unplayed': 0})
    return jsonify({
        'total_episodes': counts['total'],
        'chosen_episodes': counts['chosen'],
        'unplayed_episodes': counts['unplayed']
    })

@app.route('/logout')
def logout():
    """Çıkış yap"""
    session.clear()
    return redirect(url_for('index'))

@app.route('/health')
def health_check():
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

@app.route('/test_simple')
def test_simple():
    return jsonify({'status': 'ok', 'message': 'Server is working'})

@app.route('/test_session')
def test_session():
    return jsonify({
        'session_keys': list(session.keys()),
        'episode_counts': session.get('episode_counts', {})
    })

@app.route('/test_spotify')
def test_spotify():
    sp = get_spotify_client()
    if not sp:
        return jsonify({'error': 'Spotify not connected'})
    
    try:
        results = sp.show_episodes('40ORgVQqJWPQGRMUXmL67y', limit=5, offset=0)
        return jsonify({
            'success': True,
            'episode_count': len(results['items']),
            'episodes': [ep['name'] for ep in results['items']]
        })
    except Exception as e:
        return jsonify({'error': str(e)})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)