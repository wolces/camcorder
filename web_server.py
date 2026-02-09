#!/usr/bin/env python3
"""
web server for raspberry pi camcorder
provides video browsing, streaming, downloading, and interactive processing
organized by date and time
"""

import os
import re
import json
import subprocess
from datetime import datetime
from flask import Flask, render_template, send_file, Response, jsonify, request
from pathlib import Path

app = Flask(__name__)

# paths
VIDEO_DIR = os.path.expanduser("~/Videos")
PROCESSING_JOBS = {}  # track active processing jobs

def parse_filename_timestamp(filename):
    """extract timestamp from filename like record_2026-02-08_14-23-45.mp4"""
    match = re.match(r'record_(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})-(\d{2})\.mp4', filename)
    if match:
        date_str = match.group(1)
        hour = match.group(2)
        minute = match.group(3)
        second = match.group(4)
        return date_str, f"{hour}:{minute}"
    return None, None

def get_video_metadata(filepath, filename, video_type):
    """get metadata for a single video file"""
    stat = os.stat(filepath)
    return {
        'filename': filename,
        'type': video_type,
        'size': stat.st_size,
        'size_mb': round(stat.st_size / 1024 / 1024, 1),
        'modified': stat.st_mtime
    }

def get_videos_by_date_and_time():
    """organize videos by date and time with raw and processed versions"""
    videos_by_date = {}
    
    if os.path.exists(VIDEO_DIR):
        # iterate through date directories
        for date_dirname in sorted(os.listdir(VIDEO_DIR), reverse=True):
            date_path = os.path.join(VIDEO_DIR, date_dirname)
            
            if not os.path.isdir(date_path):
                continue
            if not re.match(r'\d{4}-\d{2}-\d{2}', date_dirname):
                continue
            
            try:
                date_obj = datetime.strptime(date_dirname, '%Y-%m-%d').date()
            except ValueError:
                continue
            
            videos_by_time = {}
            
            # iterate through time directories
            for time_dirname in sorted(os.listdir(date_path), reverse=True):
                time_path = os.path.join(date_path, time_dirname)
                
                if not os.path.isdir(time_path):
                    continue
                if not re.match(r'\d{2}-\d{2}', time_dirname):
                    continue
                
                # convert HH-MM to HH:MM for display
                time_display = time_dirname.replace('-', ':')
                
                raw_videos = []
                processed_videos = []
                
                # get raw videos
                raw_dir = os.path.join(time_path, 'raw')
                if os.path.exists(raw_dir):
                    for filename in sorted(os.listdir(raw_dir)):
                        if filename.endswith('.mp4'):
                            filepath = os.path.join(raw_dir, filename)
                            raw_videos.append(get_video_metadata(filepath, filename, 'raw'))
                
                # get processed videos
                processed_dir = os.path.join(time_path, 'processed')
                if os.path.exists(processed_dir):
                    for filename in sorted(os.listdir(processed_dir)):
                        if filename.endswith('.mp4'):
                            filepath = os.path.join(processed_dir, filename)
                            processed_videos.append(get_video_metadata(filepath, filename, 'processed'))
                
                if raw_videos or processed_videos:
                    videos_by_time[time_dirname] = {
                        'time_display': time_display,
                        'raw': raw_videos,
                        'processed': processed_videos
                    }
            
            if videos_by_time:
                videos_by_date[date_dirname] = {
                    'date_obj': date_obj,
                    'times': videos_by_time
                }
    
    return videos_by_date

@app.route('/')
def index():
    """main page showing all videos organized by date and time"""
    videos_by_date = get_videos_by_date_and_time()
    
    formatted_videos = []
    for date_str in sorted(videos_by_date.keys(), reverse=True):
        date_data = videos_by_date[date_str]
        
        times_list = []
        for time_str in sorted(date_data['times'].keys(), reverse=True):
            time_data = date_data['times'][time_str]
            times_list.append({
                'time': time_str,
                'time_display': time_data['time_display'],
                'raw': time_data['raw'],
                'processed': time_data['processed']
            })
        
        formatted_videos.append({
            'date': date_str,
            'date_display': date_data['date_obj'].strftime('%A, %B %d, %Y'),
            'times': times_list
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

@app.route('/download/<date>/<time>/<video_type>/<filename>')
def download(date, time, video_type, filename):
    """download a video file"""
    filepath = os.path.join(VIDEO_DIR, date, time, video_type, filename)
    
    if not os.path.exists(filepath):
        return "file not found", 404
    
    return send_file(filepath, as_attachment=True)

@app.route('/stream/<date>/<time>/<video_type>/<filename>')
def stream(date, time, video_type, filename):
    """stream a video file with range support"""
    filepath = os.path.join(VIDEO_DIR, date, time, video_type, filename)
    
    if not os.path.exists(filepath):
        return "file not found", 404
    
    file_size = os.path.getsize(filepath)
    range_header = request.headers.get('Range', None)
    
    if not range_header:
        return send_file(filepath, mimetype='video/mp4')
    
    byte_range = range_header.replace('bytes=', '').split('-')
    start = int(byte_range[0]) if byte_range[0] else 0
    end = int(byte_range[1]) if len(byte_range) > 1 and byte_range[1] else file_size - 1
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

@app.route('/delete/<date>/<time>/<video_type>/<filename>', methods=['POST'])
def delete(date, time, video_type, filename):
    """delete a video file"""
    filepath = os.path.join(VIDEO_DIR, date, time, video_type, filename)
    
    if not os.path.exists(filepath):
        return jsonify({'success': False, 'error': 'file not found'}), 404
    
    try:
        os.remove(filepath)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/process', methods=['POST'])
def process_video():
    """start processing a video with selected filters"""
    data = request.json
    
    date = data.get('date')
    time = data.get('time')
    filename = data.get('filename')
    filters = data.get('filters', {})
    
    input_path = os.path.join(VIDEO_DIR, date, time, 'raw', filename)
    
    if not os.path.exists(input_path):
        return jsonify({'success': False, 'error': 'source file not found'}), 404
    
    # build output filename with filter tags
    base_name = filename.replace('.mp4', '')
    tags = []
    
    if filters.get('deinterlace'):
        tags.append('deint')
    if filters.get('denoise'):
        level = filters.get('denoise_level', 'light')
        tags.append(f'dn-{level}')
    if filters.get('audio_cleanup'):
        tags.append('audio')
    if filters.get('brightness') != 0:
        tags.append(f'br{filters.get("brightness"):+d}')
    if filters.get('saturation') != 100:
        tags.append(f'sat{filters.get("saturation")}')
    if filters.get('sharpen'):
        tags.append('sharp')
    
    tag_string = '_'.join(tags) if tags else 'copy'
    output_filename = f"{base_name}_{tag_string}.mp4"
    output_path = os.path.join(VIDEO_DIR, date, time, 'processed', output_filename)
    
    # ensure processed directory exists
    os.makedirs(os.path.join(VIDEO_DIR, date, time, 'processed'), exist_ok=True)
    
    # build ffmpeg command
    cmd = ['nice', '-n', '10', '/usr/bin/ffmpeg', '-y', '-i', input_path]
    
    # build video filter chain
    vf_parts = []
    
    if filters.get('deinterlace'):
        vf_parts.append('setfield=tff,bwdif=1')
    
    if filters.get('denoise'):
        level = filters.get('denoise_level', 'light')
        if level == 'light':
            vf_parts.append('hqdn3d=1.5:1.5:6:6')
        elif level == 'medium':
            vf_parts.append('hqdn3d=3:2.5:6:5')
        elif level == 'heavy':
            vf_parts.append('hqdn3d=6:4.5:9:7')
    
    brightness = filters.get('brightness', 0)
    saturation = filters.get('saturation', 100)
    if brightness != 0 or saturation != 100:
        brightness_val = brightness / 100.0
        saturation_val = saturation / 100.0
        vf_parts.append(f'eq=brightness={brightness_val}:saturation={saturation_val}')
    
    if filters.get('sharpen'):
        vf_parts.append('unsharp=5:5:0.8:3:3:0.4')
    
    if vf_parts:
        cmd.extend(['-vf', ','.join(vf_parts)])
    
    # build audio filter chain
    af_parts = []
    
    if filters.get('audio_cleanup'):
        af_parts.append('highpass=f=80')
        af_parts.append('anlmdn=s=0.0001')
        af_parts.append('loudnorm')
    
    if af_parts:
        cmd.extend(['-af', ','.join(af_parts)])
        cmd.extend(['-c:a', 'aac', '-b:a', '192k'])
    else:
        cmd.extend(['-c:a', 'copy'])
    
    # video encoding settings
    cmd.extend([
        '-c:v', 'libx264',
        '-preset', 'medium',
        '-crf', '20',
        output_path
    ])
    
    # start processing in background
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        job_id = f"{date}_{time}_{filename}_{len(PROCESSING_JOBS)}"
        PROCESSING_JOBS[job_id] = {
            'process': process,
            'input': filename,
            'output': output_filename,
            'date': date,
            'time': time,
            'filters': filters
        }
        
        return jsonify({
            'success': True,
            'job_id': job_id,
            'output_filename': output_filename
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/processing_status/<job_id>')
def processing_status(job_id):
    """check status of a processing job"""
    if job_id not in PROCESSING_JOBS:
        return jsonify({'status': 'unknown'})
    
    job = PROCESSING_JOBS[job_id]
    process = job['process']
    
    if process.poll() is None:
        return jsonify({'status': 'processing'})
    elif process.returncode == 0:
        return jsonify({
            'status': 'complete',
            'output': job['output']
        })
    else:
        stderr = process.stderr.read().decode('utf-8') if process.stderr else ''
        return jsonify({
            'status': 'failed',
            'error': stderr
        })

@app.route('/status')
def status():
    """get system status"""
    try:
        result = subprocess.run(['pgrep', '-f', 'ffmpeg.*video0'], 
                              capture_output=True, text=True)
        is_recording = bool(result.stdout.strip())
    except:
        is_recording = False
    
    disk = os.statvfs(VIDEO_DIR)
    free_gb = (disk.f_bavail * disk.f_frsize) / (1024**3)
    
    # count active processing jobs
    active_jobs = sum(1 for job in PROCESSING_JOBS.values() 
                     if job['process'].poll() is None)
    
    return jsonify({
        'recording': is_recording,
        'free_space_gb': round(free_gb, 1),
        'processing_jobs': active_jobs
    })

if __name__ == '__main__':
    os.makedirs(VIDEO_DIR, exist_ok=True)
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)
