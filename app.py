from flask import Flask, request, render_template, send_file, jsonify, Response, stream_with_context
from flask_cors import CORS
import yt_dlp
import os
import uuid
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import logging

# লগিং সেটআপ
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# কনফিগারেশন
DOWNLOAD_FOLDER = "downloads"
MAX_CONCURRENT_DOWNLOADS = 3
CHUNK_SIZE = 8192

if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

# ডাউনলোড স্ট্যাটাস ট্র্যাকিং
download_status = {}

def get_safe_filename(title):
    """ফাইলনেম থেকে invalid characters রিমুভ করে"""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        title = title.replace(char, '_')
    return title[:100]  # ফাইলনেম length limit

def fix_shorts_url(url):
    """YouTube Shorts URL কে regular URL এ কনভার্ট করে"""
    if 'youtube.com/shorts/' in url:
        video_id = url.split('/')[-1].split('?')[0]
        return f'https://www.youtube.com/watch?v={video_id}'
    return url

def get_video_info(url):
    """ভিডিওর তথ্য fetch করে"""
    try:
        url = fix_shorts_url(url)
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info
    except Exception as e:
        logger.error(f"Error getting video info: {e}")
        return None

def get_available_formats(url):
    """ভিডিওর available ফরম্যাটগুলো রিটার্ন করে"""
    try:
        info = get_video_info(url)
        if not info:
            return []
        
        formats = []
        
        # বেস্ট কোয়ালিটি অপশন
        formats.append({
            'format_id': 'best',
            'name': '🚀 Best Quality (Auto)',
            'resolution': 'best',
            'type': 'video',
            'ext': 'mp4'
        })
        
        # MP3 অডিও অপশন
        formats.append({
            'format_id': 'mp3',
            'name': '🎵 MP3 Audio (192kbps)',
            'resolution': 'audio',
            'type': 'audio',
            'ext': 'mp3'
        })
        
        # available ভিডিও ফরম্যাটগুলো
        video_formats = []
        for f in info.get('formats', []):
            if f.get('video_ext') != 'none' and f.get('height') is not None:
                format_name = f"{f['height']}p"
                
                # ফ্রেম রেট
                if f.get('fps'):
                    format_name += f" ({int(f['fps'])}fps)"
                
                # ফাইল সাইজ
                filesize = f.get('filesize') or f.get('filesize_approx')
                if filesize:
                    size_mb = filesize / (1024 * 1024)
                    format_name += f" - {size_mb:.1f}MB"
                
                # কোডেক তথ্য
                if f.get('vcodec') and f.get('vcodec') != 'none':
                    format_name += f" ({f['vcodec'].split('.')[0]})"
                
                video_formats.append({
                    'format_id': f['format_id'],
                    'name': format_name,
                    'resolution': f'{f["height"]}p',
                    'type': 'video',
                    'height': f['height'],
                    'ext': 'mp4',
                    'filesize': filesize
                })
        
        # রেজোলিউশন অনুযায়ী সাজানো (উচ্চ থেকে নিম্ন)
        video_formats.sort(key=lambda x: x.get('height', 0), reverse=True)
        
        # ডুপ্লিকেট রিমুভ
        unique_formats = []
        seen_resolutions = set()
        
        for fmt in video_formats:
            if fmt['resolution'] not in seen_resolutions:
                unique_formats.append(fmt)
                seen_resolutions.add(fmt['resolution'])
        
        return formats + unique_formats[:10]  # সর্বোচ্চ ১০টি ফরম্যাট
        
    except Exception as e:
        logger.error(f"Error getting formats: {e}")
        return [
            {'format_id': 'best', 'name': 'Best Quality (Auto)', 'resolution': 'best', 'type': 'video', 'ext': 'mp4'},
            {'format_id': 'mp3', 'name': 'MP3 Audio', 'resolution': 'audio', 'type': 'audio', 'ext': 'mp3'}
        ]

def download_video(download_id, url, format_id, title):
    """ভিডিও ডাউনলোড করার ফাংশন"""
    try:
        url = fix_shorts_url(url)
        safe_title = get_safe_filename(title)
        output_template = os.path.join(DOWNLOAD_FOLDER, f'{download_id}_{safe_title}.%(ext)s')
        
        # প্রোগ্রেস হুক
        def progress_hook(d):
            if d['status'] == 'downloading':
                percent = d.get('_percent_str', '0%').strip()
                speed = d.get('_speed_str', 'N/A')
                total_size = d.get('_total_bytes_str', 'N/A')
                downloaded = d.get('_downloaded_bytes_str', 'N/A')
                
                download_status[download_id] = {
                    'status': 'downloading',
                    'percent': percent,
                    'speed': speed,
                    'total_size': total_size,
                    'downloaded': downloaded,
                    'filename': d.get('filename', '')
                }
                
            elif d['status'] == 'finished':
                download_status[download_id] = {
                    'status': 'finished',
                    'filename': d.get('filename', ''),
                    'final_filename': d['filename']
                }
        
        # ফরম্যাট সিলেকশন
        if format_id == 'best':
            ydl_format = 'bestvideo+bestaudio/best'
        elif format_id == 'mp3':
            ydl_format = 'bestaudio/best'
        else:
            ydl_format = f'{format_id}+bestaudio/best'
        
        ydl_opts = {
            'outtmpl': output_template,
            'format': ydl_format,
            'merge_output_format': 'mp4',
            'quiet': False,
            'no_warnings': False,
            'noplaylist': True,
            'progress_hooks': [progress_hook],
            'http_chunk_size': 10 * 1024 * 1024,  # 10MB chunks for faster download
        }
        
        # MP3 এর জন্য
        if format_id == 'mp3':
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'extractaudio': True,
            })
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            final_filename = ydl.prepare_filename(info)
            
            if format_id == 'mp3':
                final_filename = final_filename.replace('.webm', '.mp3').replace('.m4a', '.mp3').replace('.mp4', '.mp3')
            
            return final_filename
            
    except Exception as e:
        download_status[download_id] = {
            'status': 'error',
            'error': str(e)
        }
        logger.error(f"Download error: {e}")
        return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_info', methods=['POST'])
def get_info():
    """ভিডিও তথ্য fetch করে"""
    data = request.json
    url = data.get('url', '')
    
    if not url:
        return jsonify({'error': 'URL is required'}), 400
    
    try:
        info = get_video_info(url)
        if not info:
            return jsonify({'error': 'Could not fetch video information'}), 400
        
        return jsonify({
            'title': info.get('title', 'Unknown Title'),
            'duration': info.get('duration', 0),
            'thumbnail': info.get('thumbnail', ''),
            'formats': get_available_formats(url)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/start_download', methods=['POST'])
def start_download():
    """ডাউনলোড শুরু করে"""
    data = request.json
    url = data.get('url', '')
    format_id = data.get('format_id', 'best')
    title = data.get('title', 'video')
    
    if not url:
        return jsonify({'error': 'URL is required'}), 400
    
    download_id = str(uuid.uuid4())
    
    # ব্যাকগ্রাউন্ডে ডাউনলোড শুরু
    thread = threading.Thread(
        target=download_video,
        args=(download_id, url, format_id, title)
    )
    thread.daemon = True
    thread.start()
    
    return jsonify({'download_id': download_id})

@app.route('/download_status/<download_id>')
def get_download_status(download_id):
    """ডাউনলোড স্ট্যাটাস চেক করে"""
    status = download_status.get(download_id, {'status': 'unknown'})
    return jsonify(status)

@app.route('/download_file/<download_id>')
def download_file(download_id):
    """ডাউনলোড করা ফাইল ফেরত দেয়"""
    status = download_status.get(download_id, {})
    
    if status.get('status') != 'finished':
        return jsonify({'error': 'Download not completed'}), 400
    
    filename = status.get('final_filename')
    
    if not filename or not os.path.exists(filename):
        return jsonify({'error': 'File not found'}), 404
    
    # ফাইলনেম সেফ করা
    safe_filename = os.path.basename(filename).split('_', 1)[-1] if '_' in os.path.basename(filename) else os.path.basename(filename)
    
    response = send_file(
        filename,
        as_attachment=True,
        download_name=safe_filename,
        mimetype='application/octet-stream'
    )
    
    # ফাইল ডাউনলোড পর ক্লিনআপ
    @response.call_on_close
    def cleanup():
        try:
            if os.path.exists(filename):
                os.remove(filename)
                logger.info(f"Cleaned up file: {filename}")
        except Exception as e:
            logger.error(f"Error cleaning up file: {e}")
    
    return response

@app.route('/batch_download', methods=['POST'])
def batch_download():
    """মাল্টিপল URLs ডাউনলোড করে"""
    data = request.json
    urls = data.get('urls', [])
    format_id = data.get('format_id', 'best')
    
    if not urls:
        return jsonify({'error': 'URLs are required'}), 400
    
    batch_id = str(uuid.uuid4())
    download_status[batch_id] = {
        'status': 'processing',
        'total': len(urls),
        'completed': 0,
        'downloads': {}
    }
    
    def download_batch():
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_DOWNLOADS) as executor:
            futures = []
            for i, url in enumerate(urls):
                download_id = f"{batch_id}_{i}"
                future = executor.submit(download_video, download_id, url, format_id, f"video_{i}")
                futures.append((download_id, future))
            
            for download_id, future in futures:
                try:
                    result = future.result()
                    download_status[batch_id]['completed'] += 1
                    download_status[batch_id]['downloads'][download_id] = {
                        'status': 'finished' if result else 'error',
                        'filename': result
                    }
                except Exception as e:
                    download_status[batch_id]['downloads'][download_id] = {
                        'status': 'error',
                        'error': str(e)
                    }
            
            download_status[batch_id]['status'] = 'finished'
    
    thread = threading.Thread(target=download_batch)
    thread.daemon = True
    thread.start()
    
    return jsonify({'batch_id': batch_id})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)