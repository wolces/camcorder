#!/usr/bin/env python3
"""
web server for raspberry pi camcorder
provides video browsing, streaming, and downloading
"""

import os
import mimetypes
from flask import Flask, render_template, send_file, Response, jsonify, request
from pathlib import Path
import subprocess

app = Flask(__name__)

# paths
VIDEO_DIR = os.path.expanduser("~/Videos")
DEINTERLACED_DIR = os.path.join(VIDEO_DIR, "deinterlaced")

def get_video_list(directory):
    """get list of video files with metadata"""
    videos = []
    if not os.path.exists(directory):
        return videos
    
    for filename in sorted(os.listdir(directory), reverse=True):
        if filename.endswith('.mp4'):
            filepath = os.path.join(directory, filename)
            stat = os.stat(filepath)
            videos.append({
                'filename': filename,
                'size': stat.st_size,
                'size_mb': round(stat.st_size / 1024 / 1024, 1),
                'modified': stat.st_mtime
            })
    return videos

@app.route('/')
def index():
    """main page showing all videos"""
    masters = get_video_list(VIDEO_DIR)
    deinterlaced = get_video_list(DEINTERLACED_DIR)
    
    # get disk usage
    disk = os.statvfs(VIDEO_DIR)
    total_gb = (disk.f_blocks * disk.f_frsize) / (1024**3)
    free_gb = (disk.f_bavail * disk.f_frsize) / (1024**3)
    used_gb = total_gb - free_gb
    
    return render_template('index.html', 
                         masters=masters,
                         deinterlaced=deinterlaced,
                         disk_used=round(used_gb, 1),
                         disk_total=round(total_gb, 1))

@app.route('/download/<path:filename>')
def download(filename):
    """download a video file"""
    # check both directories
    filepath = os.path.join(VIDEO_DIR, filename)
    if not os.path.exists(filepath):
        filepath = os.path.join(DEINTERLACED_DIR, filename)
    
    if not os.path.exists(filepath):
        return "file not found", 404
    
    return send_file(filepath, as_attachment=True)

@app.route('/stream/<path:filename>')
def stream(filename):
    """stream a video file with range support"""
    # check both directories
    filepath = os.path.join(VIDEO_DIR, filename)
    if not os.path.exists(filepath):
        filepath = os.path.join(DEINTERLACED_DIR, filename)
    
    if not os.path.exists(filepath):
        return "file not found", 404
    
    # get file size
    file_size = os.path.getsize(filepath)
    
    # parse range header
    range_header = request.headers.get('Range', None)
    if not range_header:
        # no range, send full file
        return send_file(filepath, mimetype='video/mp4')
    
    # parse range
    byte_range = range_header.replace('bytes=', '').split('-')
    start = int(byte_range[0]) if byte_range[0] else 0
    end = int(byte_range[1]) if len(byte_range) > 1 and byte_range[1] else file_size - 1
    
    # read chunk
    chunk_size = end - start + 1
    
    def generate():
        with open(filepath, 'rb') as f:
            f.seek(start)
            remaining = chunk_size
            while remaining > 0:
                read_size = min(8192, remaining)
                data = f.read(read_size)
                if not data:
                    break
                remaining -= len(data)
                yield data
    
    response = Response(generate(), 206, mimetype='video/mp4')
    response.headers.add('Content-Range', f'bytes {start}-{end}/{file_size}')
    response.headers.add('Accept-Ranges', 'bytes')
    response.headers.add('Content-Length', chunk_size)
    return response

@app.route('/delete/<path:filename>', methods=['POST'])
def delete(filename):
    """delete a video file"""
    # check both directories
    filepath = os.path.join(VIDEO_DIR, filename)
    if not os.path.exists(filepath):
        filepath = os.path.join(DEINTERLACED_DIR, filename)
    
    if not os.path.exists(filepath):
        return jsonify({'success': False, 'error': 'file not found'}), 404
    
    try:
        os.remove(filepath)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/status')
def status():
    """get system status"""
    # check if recording
    try:
        result = subprocess.run(['pgrep', '-f', 'ffmpeg.*video0'], 
                              capture_output=True, text=True)
        is_recording = bool(result.stdout.strip())
    except:
        is_recording = False
    
    # get disk usage
    disk = os.statvfs(VIDEO_DIR)
    free_gb = (disk.f_bavail * disk.f_frsize) / (1024**3)
    
    return jsonify({
        'recording': is_recording,
        'free_space_gb': round(free_gb, 1)
    })

if __name__ == '__main__':
    # ensure directories exist
    os.makedirs(VIDEO_DIR, exist_ok=True)
    os.makedirs(DEINTERLACED_DIR, exist_ok=True)
    
    # run on all interfaces, port 80 (requires root or capabilities)
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)
