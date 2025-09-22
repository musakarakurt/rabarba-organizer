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

# Kullanıcı verilerini sakla
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
        except:
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
    """Bölüm detaylarını çıkarır - TAM BİLGİLER"""
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
    match = re.search(r'(\d{3,4})', name)
    return int(match.group(1)) if match else 0

def extract_part(name):
    match = re.search(r'\s([AB])(?:\s|$|\))', name)
    return match.group(1) if match else None

def contains_target_guest(description, episode_number):
    """Açıklamada hedef konukların olup olmadığını kontrol eder - TÜM BÖLÜMLERDE FİLTRELE"""
    if not description:
        return False
        
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
        user_id = user['id']
        
        episode_data = user_data.get(user_id, {})
        counts = episode_data.get('counts', {'total': 0, 'chosen': 0, 'unplayed': 0})
        
        return render_template('dashboard.html', 
                             user=user,
                             counts=counts)
    except Exception as e:
        session.clear()
        return redirect(url_for('login'))

@app.route('/load_episodes')
def load_episodes():
    """TÜM bölümleri yükle - 2389 BÖLÜM TAMAMEN"""
    sp = get_spotify_client()
    if not sp:
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        user_id = get_user_id()
        if not user_id:
            return jsonify({'error': 'User not found'}), 401
        
        show_id = '40ORgVQqJWPQGRMUXmL67y'
        all_episodes = []
        
        print("TÜM bölümler yükleniyor...")
        
        # TÜM sayfaları dolaş - 2389 bölüm için
        offset = 0
        limit = 50
        
        while True:
            print(f"Offset {offset} yükleniyor...")
            
            results = sp.show_episodes(show_id, limit=limit, offset=offset)
            
            if not results or 'items' not in results or not results['items']:
                print("Sayfa boş, duruyorum...")
                break
                
            page_episodes = len(results['items'])
            print(f"Offset {offset}: {page_episodes} bölüm bulundu")
            
            for episode in results['items']:
                if episode:
                    episode_details = get_episode_details(episode)
                    if episode_details and episode_details['episode_number'] > 0:
                        all_episodes.append(episode_details)
            
            # Eğer bu sayfa tam dolu değilse, daha fazla sayfa yok
            if page_episodes < limit:
                print(f"Son sayfaya ulaşıldı. Toplam: {len(all_episodes)} bölüm")
                break
            
            offset += limit
            
            # 1 saniye bekle (Spotify API rate limit)
            time.sleep(1)
            
            # Safety break (max 3000 bölüm)
            if offset > 2500:
                print("Safety break: 2500 offset'e ulaşıldı")
                break
        
        print(f"✅ Toplam {len(all_episodes)} bölüm yüklendi")
        
        if not all_episodes:
            return jsonify({'error': 'No episodes loaded'}), 500
        
        # Bölüm numaralarını kontrol et
        episode_numbers = [ep['episode_number'] for ep in all_episodes]
        if episode_numbers:
            min_ep = min(episode_numbers)
            max_ep = max(episode_numbers)
            print(f"Bölüm aralığı: {min_ep} - {max_ep}")
        
        # Bölümleri sırala
        sorted_episodes = sort_episodes(all_episodes)
        
        # Filtreleme yap
        chosen_episodes = []
        for ep in sorted_episodes:
            if contains_target_guest(ep['description'], ep['episode_number']):
                chosen_episodes.append(ep)
        
        print(f"✅ Filtreleme sonucu: {len(chosen_episodes)} bölüm")
        
        # Verileri kaydet
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
            'message': f'✅ {len(sorted_episodes)} bölüm yüklendi! {len(chosen_episodes)} bölüm filtrelendi.'
        })
    
    except Exception as e:
        return jsonify({'error': f'Error: {str(e)}'}), 500

@app.route('/view_lists')
def view_lists():
    """Listeleri görüntüle - TÜM LİSTE TEK SAYFADA"""
    user_id = get_user_id()
    if not user_id:
        return redirect(url_for('login'))
    
    episode_data = user_data.get(user_id, {})
    
    if not episode_data:
        return render_template('view_lists.html',
                             all_episodes=[],
                             chosen_episodes=[],
                             unplayed_episodes=[],
                             total_count=0,
                             chosen_count=0,
                             unplayed_count=0,
                             message="Henüz bölüm yüklenmedi. 'Bölümleri Yükle' butonuna tıklayın.")
    
    # TÜM bölümleri göster - SAYFALAMA YOK
    all_episodes = episode_data.get('all_episodes', [])
    chosen_episodes = episode_data.get('chosen_episodes', [])
    unplayed_episodes = episode_data.get('unplayed_episodes', [])
    
    return render_template('view_lists.html',
                         all_episodes=all_episodes,
                         chosen_episodes=chosen_episodes,
                         unplayed_episodes=unplayed_episodes,
                         total_count=len(all_episodes),
                         chosen_count=len(chosen_episodes),
                         unplayed_count=len(unplayed_episodes))

@app.route('/sync_playlists')
def sync_playlists():
    """Spotify listelerini senkronize et - ONAYLI"""
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
            'message': f'✅ Spotify listeleri güncellendi! Seçilen: {len(chosen_episodes)} bölüm, Oynatılmayan: {len(unplayed_episodes)} bölüm'
        })
    
    except Exception as e:
        return jsonify({'error': f'Sync error: {str(e)}'}), 500

def create_or_find_playlist(sp, user_id, playlist_name):
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
        user_id = get_user_id()
        if not user_id:
            return jsonify({'error': 'Not authenticated'}), 401
        
        episode_data = user_data.get(user_id, {})
        if not episode_data:
            return jsonify({'error': 'No episode data'}), 400
        
        unplayed_episodes = episode_data.get('unplayed_episodes', [])
        new_unplayed = [ep for ep in unplayed_episodes if ep['episode_number'] != episode_number]
        
        episode_data['unplayed_episodes'] = new_unplayed
        episode_data['counts']['unplayed'] = len(new_unplayed)
        user_data[user_id] = episode_data
        
        return jsonify({'success': True, 'remaining': len(new_unplayed)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)