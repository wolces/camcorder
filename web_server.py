#!/usr/bin/env python3
"""
web server for raspberry pi camcorder
provides video browsing, streaming, and downloading
organized by date
"""

import os
import re
from datetime import datetime
from flask import Flask, render_template, send_file, Response, jsonify, request
from pathlib import Path
import subprocess

app = Flask(__name__)

# paths
VIDEO_DIR = os.path.expanduser("~/Videos")

def parse_filename_date(filename):
    """extract date from filename like record_2026-02-08_14-23-45.mp4"""
    match = re.match(r'record_(\d{4}-\d{2}-\d{2})_', filename)
    if match:
        date_str = match.group(1)
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    return None

def get_video_metadata(filepath, filename, video_type):
    """get metadata for a single video file"""
    stat = os.stat(filepath)
    return {
        'filename': filename,
        'type': video_type,  # 'raw' or 'deinterlaced'
        'size': stat.st_size,
        'size_mb': round(stat.st_size / 1024 / 1024, 1),
        'modified': stat.st_mtime
    }

def get_videos_by_date():
    """organize videos by date with raw and deinterlaced versions"""
    videos_by_date = {}
    
    # scan all date directories
    if os.path.exists(VIDEO_DIR):
        for date_dirname in sorted(os.listdir(VIDEO_DIR), reverse=True):
            date_path = os.path.join(VIDEO_DIR, date_dirname)
            
            # skip if not a directory or doesn't match YYYY-MM-DD format
            if not os.path.isdir(date_path):
                continue
            if not re.match(r'\d{4}-\d{2}-\d{2}', date_dirname):
                continue
            
            try:
                date = datetime.strptime(date_dirname, '%Y-%m-%d').date()
            except ValueError:
                continue
            
            raw_videos = []
            deinterlaced_videos = []
            
            # get raw videos
            raw_dir = os.path.join(date_path, 'raw')
            if os.path.exists(raw_dir):
                for filename in sorted(os.listdir(raw_dir), reverse=True):
                    if filename.endswith('.mp4'):
                        filepath = os.path.join(raw_dir, filename)
                        raw_videos.append(get_video_metadata(filepath, filename, 'raw'))
            
            # get deinterlaced videos
            deinterlaced_dir = os.path.join(date_path, 'deinterlaced')
            if os.path.exists(deinterlaced_dir):
                for filename in sorted(os.listdir(deinterlaced_dir), reverse=True):
                    if filename.endswith('.mp4'):
                        filepath = os.path.join(deinterlaced_dir, filename)
                        deinterlaced_videos.append(get_video_metadata(filepath, filename, 'deinterlaced'))
            
            # only include dates that have at least one video
            if raw_videos or deinterlaced_videos:
                videos_by_date[date] = {
                    'raw': raw_videos,
                    'deinterlaced': deinterlaced_videos
                }
    
    return videos_by_date

@app.route('/')
def index():
    """main page showing all videos organized by date"""
    videos_by_date = get_videos_by_date()
    
    # format for template
    formatted_videos = []
    for date in sorted(videos_by_date.keys(), reverse=True):
        videos = videos_by_date[date]
        formatted_videos.append({
            'date': date.strftime('%Y-%m-%d'),
            'date_display': date.strftime('%A, %B %d, %Y'),
            'raw': videos['raw'],
            'deinterlaced': videos['deinterlaced']
        })
    
    # get disk usage
    disk = os.statvfs(VIDEO_DIR)
    total_gb = (disk.f_blocks * disk.f_frsize) / (1024**3)
    free_gb = (disk.f_bavail * disk.f_frsize) / (1024**3)
    used_gb = total_gb - free_gb
    
    return render_template('index.html', 
                         videos_by_date=formatted_videos,
                         disk_used=round(used_gb, 1),
                         disk_total=round(total_gb, 1))

@app.route('/download/<date>/<video_type>/<filename>')
def download(date, video_type, filename):
    """download a video file"""
    filepath = os.path.join(VIDEO_DIR, date, video_type, filename)
    
    if not os.path.exists(filepath):
        return "file not found", 404
    
    return send_file(filepath, as_attachment=True)

@app.route('/stream/<date>/<video_type>/<filename>')
def stream(date, video_type, filename):
    """stream a video file with range support"""
    filepath = os.path.join(VIDEO_DIR, date, video_type, filename)
    
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

@app.route('/delete/<date>/<video_type>/<filename>', methods=['POST'])
def delete(date, video_type, filename):
    """delete a video file"""
    filepath = os.path.join(VIDEO_DIR, date, video_type, filename)
    
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
    # ensure base directory exists
    os.makedirs(VIDEO_DIR, exist_ok=True)
    
    # run on all interfaces, port 8080
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)
