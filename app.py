from flask import Flask, request, render_template, send_file, jsonify
import yt_dlp
import os
import uuid
import threading
import logging
import tempfile

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Render-compatible download folder (use temp directory)
DOWNLOAD_FOLDER = tempfile.gettempdir()

# FFmpeg path for Render
FFMPEG_PATH = '/usr/local/bin/ffmpeg'

def get_safe_filename(title):
    """Safe filename creation"""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        title = title.replace(char, '_')
    return title[:100]

def fix_shorts_url(url):
    """Fix YouTube Shorts URLs"""
    if 'youtube.com/shorts/' in url:
        video_id = url.split('/')[-1].split('?')[0]
        return f'https://www.youtube.com/watch?v={video_id}'
    return url

def get_video_info(url):
    """Get video information"""
    try:
        url = fix_shorts_url(url)
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info
    except Exception as e:
        logger.error(f"Error getting video info: {e}")
        return None

def get_available_formats(url):
    """Get available formats"""
    try:
        info = get_video_info(url)
        if not info:
            return []
        
        formats = []
        
        # Best quality options
        formats.append({
            'format_id': 'best',
            'name': '🚀 Best Quality (Auto)',
            'type': 'video',
            'ext': 'mp4'
        })
        
        # Audio options
        formats.append({
            'format_id': 'mp3',
            'name': '🎵 MP3 Audio (192kbps)',
            'type': 'audio',
            'ext': 'mp3'
        })
        
        # Video formats
        for f in info.get('formats', []):
            if f.get('height') and f.get('acodec') != 'none' and f.get('vcodec') != 'none':
                format_name = f"{f['height']}p"
                if f.get('fps'):
                    format_name += f" ({int(f['fps'])}fps)"
                
                filesize = f.get('filesize') or f.get('filesize_approx')
                if filesize:
                    size_mb = filesize / (1024 * 1024)
                    format_name += f" - {size_mb:.1f}MB"
                
                formats.append({
                    'format_id': f['format_id'],
                    'name': format_name,
                    'type': 'video',
                    'ext': 'mp4',
                    'height': f['height']
                })
        
        # Remove duplicates and sort
        unique_formats = []
        seen = set()
        for fmt in formats:
            if fmt['format_id'] not in seen:
                unique_formats.append(fmt)
                seen.add(fmt['format_id'])
        
        return sorted(unique_formats, key=lambda x: x.get('height', 0), reverse=True)[:10]
        
    except Exception as e:
        logger.error(f"Error getting formats: {e}")
        return [
            {'format_id': 'best', 'name': 'Best Quality', 'type': 'video', 'ext': 'mp4'},
            {'format_id': 'mp3', 'name': 'MP3 Audio', 'type': 'audio', 'ext': 'mp3'},
        ]

# Download status tracking
download_status = {}

def download_video(download_id, url, format_id, title):
    """Download video with progress tracking"""
    try:
        url = fix_shorts_url(url)
        safe_title = get_safe_filename(title)
        output_path = os.path.join(DOWNLOAD_FOLDER, f'{download_id}_{safe_title}.%(ext)s')
        
        def progress_hook(d):
            if d['status'] == 'downloading':
                download_status[download_id] = {
                    'status': 'downloading',
                    'percent': d.get('_percent_str', '0%'),
                    'speed': d.get('_speed_str', 'N/A'),
                    'total_size': d.get('_total_bytes_str', 'N/A'),
                    'downloaded': d.get('_downloaded_bytes_str', 'N/A'),
                }
            elif d['status'] == 'finished':
                download_status[download_id] = {
                    'status': 'finished',
                    'filename': d['filename']
                }
        
        # YouTube DL options
        ydl_opts = {
            'outtmpl': output_path,
            'quiet': False,
            'no_warnings': False,
            'progress_hooks': [progress_hook],
            'ffmpeg_location': FFMPEG_PATH,
        }
        
        # Format selection
        if format_id == 'best':
            ydl_opts['format'] = 'bestvideo+bestaudio/best'
        elif format_id == 'mp3':
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            })
        else:
            ydl_opts['format'] = f'{format_id}+bestaudio/best'
        
        ydl_opts['merge_output_format'] = 'mp4'
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            final_filename = ydl.prepare_filename(info)
            
            if format_id == 'mp3':
                final_filename = final_filename.replace('.webm', '.mp3').replace('.m4a', '.mp3')
            
            return final_filename
            
    except Exception as e:
        download_status[download_id] = {
            'status': 'error',
            'error': str(e)
        }
        logger.error(f"Download error: {e}")
        return None

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/get_info', methods=['POST'])
def get_info():
    """Get video information"""
    try:
        data = request.get_json()
        url = data.get('url', '').strip()
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
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
        logger.error(f"Error in get_info: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/start_download', methods=['POST'])
def start_download():
    """Start download process"""
    try:
        data = request.get_json()
        url = data.get('url', '').strip()
        format_id = data.get('format_id', 'best')
        title = data.get('title', 'video')
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        download_id = str(uuid.uuid4())
        
        # Start download in background thread
        thread = threading.Thread(
            target=download_video,
            args=(download_id, url, format_id, title),
            daemon=True
        )
        thread.start()
        
        return jsonify({
            'download_id': download_id,
            'message': 'Download started successfully'
        })
        
    except Exception as e:
        logger.error(f"Error in start_download: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/download_status/<download_id>')
def download_status_check(download_id):
    """Check download status"""
    try:
        status = download_status.get(download_id, {'status': 'unknown'})
        return jsonify(status)
    except Exception as e:
        logger.error(f"Error in download_status: {e}")
        return jsonify({'status': 'error', 'error': str(e)}), 500

@app.route('/download_file/<download_id>')
def download_file(download_id):
    """Download completed file"""
    try:
        status = download_status.get(download_id, {})
        
        if status.get('status') != 'finished':
            return jsonify({'error': 'Download not completed'}), 400
        
        filename = status.get('filename')
        if not filename or not os.path.exists(filename):
            return jsonify({'error': 'File not found'}), 404
        
        # Create safe filename for download
        safe_filename = get_safe_filename(f"video_{download_id[:8]}")
        if filename.endswith('.mp3'):
            safe_filename += '.mp3'
        else:
            safe_filename += '.mp4'
        
        response = send_file(
            filename,
            as_attachment=True,
            download_name=safe_filename
        )
        
        # Cleanup after download
        @response.call_on_close
        def cleanup():
            try:
                if os.path.exists(filename):
                    os.remove(filename)
                    logger.info(f"Cleaned up file: {filename}")
            except Exception as e:
                logger.error(f"Error cleaning up: {e}")
        
        return response
        
    except Exception as e:
        logger.error(f"Error in download_file: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

# Health check endpoint for Render
@app.route('/health')
def health_check():
    return jsonify({'status': 'healthy', 'message': 'Server is running'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
