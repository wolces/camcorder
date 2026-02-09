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
import tempfile
import hashlib
import time
from datetime import datetime
from flask import Flask, render_template, send_file, Response, jsonify, request
from pathlib import Path

app = Flask(__name__)

# paths
VIDEO_DIR = os.path.expanduser("~/Videos")
PREVIEW_CACHE_DIR = os.path.join(tempfile.gettempdir(), "camcorder_previews")
PROCESSING_JOBS = {}  # track active processing jobs

os.makedirs(PREVIEW_CACHE_DIR, exist_ok=True)


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
    meta = {
        'filename': filename,
        'type': video_type,
        'size': stat.st_size,
        'size_mb': round(stat.st_size / 1024 / 1024, 1),
        'modified': stat.st_mtime,
        'created_display': datetime.fromtimestamp(stat.st_mtime).strftime('%b %d, %Y at %I:%M %p'),
    }

    # for processed videos, parse the filename tags into readable descriptions
    if video_type == 'processed':
        meta['filter_tags'] = parse_filter_tags(filename)

    return meta


# map of filename tag prefixes to human-readable labels
FILTER_TAG_MAP = {
    'deint-bwdif': 'Deinterlace (BWDIF)',
    'deint-yadif': 'Deinterlace (Yadif)',
    'deint-estdif': 'Deinterlace (ESTDIF)',
    'deint-kerndeint': 'Deinterlace (Kerndeint)',
    'deint': 'Deinterlaced',
    'sharp': 'Sharpened',
    'wb': 'White balance adjusted',
    'audio': 'Audio cleanup',
    'copy': 'No filters (copy)',
    'default': 'Default processing',
}


def parse_filter_tags(filename):
    """parse filter tags from processed filename into readable list.
    e.g. 'record_2026-02-08_14-23-45_deint-bwdif_dn-s3.0_sharp.mp4'
    returns ['Deinterlace (BWDIF)', 'Denoise: spatial 3.0', 'Sharpened']
    """
    # strip the base recording name prefix and .mp4 suffix
    name = filename.replace('.mp4', '')
    # find the part after the timestamp: record_YYYY-MM-DD_HH-MM-SS_<tags>
    match = re.match(r'record_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_(.*)', name)
    if not match:
        return []

    tag_string = match.group(1)
    tags = tag_string.split('_')
    descriptions = []

    for tag in tags:
        # check exact matches first
        if tag in FILTER_TAG_MAP:
            descriptions.append(FILTER_TAG_MAP[tag])
            continue

        # denoise: dn-s3.0
        m = re.match(r'dn-s([\d.]+)', tag)
        if m:
            descriptions.append(f'Denoise: spatial {m.group(1)}')
            continue

        # brightness: br+10 or br-5
        m = re.match(r'br([+-]\d+)', tag)
        if m:
            descriptions.append(f'Brightness: {m.group(1)}')
            continue

        # contrast: ct120
        m = re.match(r'ct(\d+)', tag)
        if m:
            descriptions.append(f'Contrast: {m.group(1)}%')
            continue

        # saturation: sat120
        m = re.match(r'sat(\d+)', tag)
        if m:
            descriptions.append(f'Saturation: {m.group(1)}%')
            continue

        # gamma: gm120
        m = re.match(r'gm(\d+)', tag)
        if m:
            descriptions.append(f'Gamma: {m.group(1)}%')
            continue

        # crop: crop4x3, crop16x9, crop1x1
        m = re.match(r'crop(\d+)x(\d+)', tag)
        if m:
            descriptions.append(f'Cropped to {m.group(1)}:{m.group(2)}')
            continue

        # fallback: show the raw tag
        if tag:
            descriptions.append(tag)

    return descriptions


def get_video_duration(filepath):
    """get video duration in seconds using ffprobe"""
    try:
        result = subprocess.run([
            'ffprobe', '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            filepath
        ], capture_output=True, text=True, timeout=10)
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception:
        pass
    return 60.0  # fallback


def get_videos_by_date_and_time():
    """organize videos by date and time with raw and processed versions"""
    videos_by_date = {}

    if os.path.exists(VIDEO_DIR):
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

            for time_dirname in sorted(os.listdir(date_path), reverse=True):
                time_path = os.path.join(date_path, time_dirname)

                if not os.path.isdir(time_path):
                    continue
                if not re.match(r'\d{2}-\d{2}', time_dirname):
                    continue

                time_display = time_dirname.replace('-', ':')

                raw_videos = []
                processed_videos = []

                raw_dir = os.path.join(time_path, 'raw')
                if os.path.exists(raw_dir):
                    for filename in sorted(os.listdir(raw_dir)):
                        if filename.endswith('.mp4'):
                            filepath = os.path.join(raw_dir, filename)
                            raw_videos.append(get_video_metadata(filepath, filename, 'raw'))

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


def build_vf_chain(filters):
    """build ffmpeg video filter chain from filter dict"""
    vf_parts = []

    # deinterlace
    if filters.get('deinterlace'):
        method = filters.get('deinterlace_method', 'bwdif')
        if method == 'bwdif':
            vf_parts.append('setfield=tff,bwdif=1')
        elif method == 'yadif':
            mode = filters.get('deinterlace_mode', '1')  # 0=frame, 1=field
            vf_parts.append(f'setfield=tff,yadif={mode}')
        elif method == 'estdif':
            vf_parts.append('setfield=tff,estdif')
        elif method == 'kerndeint':
            vf_parts.append('kerndeint')

    # denoise
    if filters.get('denoise'):
        spatial = filters.get('denoise_spatial', 3.0)
        temporal = filters.get('denoise_temporal', 6.0)
        vf_parts.append(f'hqdn3d={spatial}:{spatial * 0.8:.1f}:{temporal}:{temporal * 0.8:.1f}')

    # white balance / color temperature
    color_temp = filters.get('color_temp', 0)
    tint = filters.get('tint', 0)
    if color_temp != 0 or tint != 0:
        # color temperature: warm = more red/yellow, cool = more blue
        # tint: positive = more magenta, negative = more green
        r_gain = 1.0 + (color_temp / 200.0)
        b_gain = 1.0 - (color_temp / 200.0)
        g_gain = 1.0 - (tint / 200.0)
        # clamp values
        r_gain = max(0.5, min(2.0, r_gain))
        b_gain = max(0.5, min(2.0, b_gain))
        g_gain = max(0.5, min(2.0, g_gain))
        vf_parts.append(f'colorbalance=rs={color_temp / 200.0:.3f}:bs={-color_temp / 200.0:.3f}:gm={-tint / 200.0:.3f}:bm={tint / 200.0:.3f}')

    # brightness, contrast, saturation, gamma
    brightness = filters.get('brightness', 0)
    contrast = filters.get('contrast', 100)
    saturation = filters.get('saturation', 100)
    gamma = filters.get('gamma', 100)
    if brightness != 0 or contrast != 100 or saturation != 100 or gamma != 100:
        eq_parts = []
        if brightness != 0:
            eq_parts.append(f'brightness={brightness / 100.0:.3f}')
        if contrast != 100:
            eq_parts.append(f'contrast={contrast / 100.0:.2f}')
        if saturation != 100:
            eq_parts.append(f'saturation={saturation / 100.0:.2f}')
        if gamma != 100:
            eq_parts.append(f'gamma={gamma / 100.0:.2f}')
        vf_parts.append('eq=' + ':'.join(eq_parts))

    # sharpen
    if filters.get('sharpen'):
        strength = filters.get('sharpen_luma', 0.8)
        chroma = filters.get('sharpen_chroma', 0.4)
        vf_parts.append(f'unsharp=5:5:{strength:.1f}:3:3:{chroma:.1f}')

    # crop (for aspect ratio adjustment)
    crop = filters.get('crop')
    if crop and crop != 'none':
        if crop == '4:3':
            vf_parts.append('crop=ih*4/3:ih')
        elif crop == '16:9':
            vf_parts.append('crop=ih*16/9:ih')
        elif crop == '1:1':
            vf_parts.append('crop=ih:ih')

    return ','.join(vf_parts) if vf_parts else None


def build_af_chain(filters):
    """build ffmpeg audio filter chain from filter dict"""
    af_parts = []

    if filters.get('audio_cleanup'):
        # highpass
        highpass_freq = filters.get('highpass_freq', 80)
        if highpass_freq > 0:
            af_parts.append(f'highpass=f={highpass_freq}')

        # lowpass
        lowpass_freq = filters.get('lowpass_freq', 0)
        if lowpass_freq > 0:
            af_parts.append(f'lowpass=f={lowpass_freq}')

        # noise reduction
        nr_strength = filters.get('noise_reduction', 0.0001)
        if nr_strength > 0:
            af_parts.append(f'anlmdn=s={nr_strength}')

        # de-hum (notch filter at 60hz for ntsc regions)
        if filters.get('dehum'):
            dehum_freq = filters.get('dehum_freq', 60)
            af_parts.append(f'bandreject=f={dehum_freq}:width_type=q:width=5')
            # also remove harmonics
            for harmonic in [2, 3, 4]:
                af_parts.append(f'bandreject=f={dehum_freq * harmonic}:width_type=q:width=5')

        # loudness normalization
        if filters.get('loudnorm', True):
            af_parts.append('loudnorm')

    return ','.join(af_parts) if af_parts else None


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


@app.route('/video_info/<date>/<time>/<filename>')
def video_info(date, time, filename):
    """return video metadata including duration"""
    filepath = os.path.join(VIDEO_DIR, date, time, 'raw', filename)

    if not os.path.exists(filepath):
        return jsonify({'error': 'not found'}), 404

    duration = get_video_duration(filepath)

    return jsonify({
        'duration': round(duration, 2),
        'filename': filename
    })


@app.route('/preview', methods=['POST'])
def preview_frame():
    """extract a single frame from a video and apply filters, return as jpeg.
    used for the live preview in the processing modal."""
    data = request.json

    date = data.get('date')
    time_slot = data.get('time')
    filename = data.get('filename')
    filters = data.get('filters', {})
    seek_seconds = data.get('seek', 2)  # default to 2 seconds in

    input_path = os.path.join(VIDEO_DIR, date, time_slot, 'raw', filename)

    if not os.path.exists(input_path):
        return jsonify({'success': False, 'error': 'source file not found'}), 404

    # build a cache key from the filter state
    filter_key = json.dumps(filters, sort_keys=True) + f"_seek{seek_seconds}"
    cache_hash = hashlib.md5((input_path + filter_key).encode()).hexdigest()
    cache_path = os.path.join(PREVIEW_CACHE_DIR, f"{cache_hash}.jpg")

    # return cached version if fresh (< 30 seconds old)
    if os.path.exists(cache_path):
        age = time.time() - os.path.getmtime(cache_path)
        if age < 30:
            return send_file(cache_path, mimetype='image/jpeg')

    # build ffmpeg command to extract and filter one frame
    # -ss placed after -i for accurate frame-level seeking (pre-input seeks
    # to nearest keyframe which often lands on frame 0 for sparse-keyframe files)
    cmd = [
        '/usr/bin/ffmpeg', '-y',
        '-i', input_path,
        '-ss', str(seek_seconds),
        '-frames:v', '1',
    ]

    vf_chain = build_vf_chain(filters)
    if vf_chain:
        cmd.extend(['-vf', vf_chain])

    cmd.extend([
        '-q:v', '3',
        '-f', 'image2',
        cache_path
    ])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            return jsonify({'success': False, 'error': result.stderr[-500:]}), 500

        if not os.path.exists(cache_path):
            return jsonify({'success': False, 'error': 'frame extraction produced no output'}), 500

        return send_file(cache_path, mimetype='image/jpeg')
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': 'preview timed out'}), 504
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/thumbnail/<date>/<time>/<filename>')
def thumbnail(date, time, filename):
    """extract a thumbnail from a raw video (unfiltered)"""
    input_path = os.path.join(VIDEO_DIR, date, time, 'raw', filename)

    if not os.path.exists(input_path):
        return "not found", 404

    cache_path = os.path.join(PREVIEW_CACHE_DIR, f"thumb_{date}_{time}_{filename}.jpg")

    if os.path.exists(cache_path):
        return send_file(cache_path, mimetype='image/jpeg')

    cmd = [
        '/usr/bin/ffmpeg', '-y',
        '-i', input_path,
        '-ss', '2',
        '-frames:v', '1',
        '-q:v', '5',
        '-f', 'image2',
        cache_path
    ]

    try:
        subprocess.run(cmd, capture_output=True, timeout=10)
        if os.path.exists(cache_path):
            return send_file(cache_path, mimetype='image/jpeg')
        return "failed to extract thumbnail", 500
    except Exception:
        return "thumbnail error", 500


@app.route('/process', methods=['POST'])
def process_video():
    """start processing a video with selected filters"""
    data = request.json

    date = data.get('date')
    time_slot = data.get('time')
    filename = data.get('filename')
    filters = data.get('filters', {})

    input_path = os.path.join(VIDEO_DIR, date, time_slot, 'raw', filename)

    if not os.path.exists(input_path):
        return jsonify({'success': False, 'error': 'source file not found'}), 404

    # build output filename with filter tags
    base_name = filename.replace('.mp4', '')
    tags = []

    if filters.get('deinterlace'):
        method = filters.get('deinterlace_method', 'bwdif')
        tags.append(f'deint-{method}')
    if filters.get('denoise'):
        s = filters.get('denoise_spatial', 3.0)
        tags.append(f'dn-s{s}')
    if filters.get('color_temp', 0) != 0 or filters.get('tint', 0) != 0:
        tags.append('wb')
    if filters.get('brightness', 0) != 0:
        tags.append(f'br{filters.get("brightness"):+d}')
    if filters.get('contrast', 100) != 100:
        tags.append(f'ct{filters.get("contrast")}')
    if filters.get('saturation', 100) != 100:
        tags.append(f'sat{filters.get("saturation")}')
    if filters.get('gamma', 100) != 100:
        tags.append(f'gm{filters.get("gamma")}')
    if filters.get('sharpen'):
        tags.append('sharp')
    if filters.get('audio_cleanup'):
        tags.append('audio')
    if filters.get('crop') and filters.get('crop') != 'none':
        tags.append(f'crop{filters.get("crop").replace(":", "x")}')

    tag_string = '_'.join(tags) if tags else 'copy'
    output_filename = f"{base_name}_{tag_string}.mp4"
    output_path = os.path.join(VIDEO_DIR, date, time_slot, 'processed', output_filename)

    os.makedirs(os.path.join(VIDEO_DIR, date, time_slot, 'processed'), exist_ok=True)

    # build ffmpeg command
    cmd = ['nice', '-n', '10', '/usr/bin/ffmpeg', '-y', '-i', input_path]

    vf_chain = build_vf_chain(filters)
    if vf_chain:
        cmd.extend(['-vf', vf_chain])

    af_chain = build_af_chain(filters)
    if af_chain:
        cmd.extend(['-af', af_chain])
        cmd.extend(['-c:a', 'aac', '-b:a', str(filters.get('audio_bitrate', 192)) + 'k'])
    else:
        cmd.extend(['-c:a', 'copy'])

    # video encoding settings
    preset = filters.get('preset', 'medium')
    cmd.extend(['-c:v', 'libx264', '-preset', preset])

    # quality mode: crf or target bitrate
    quality_mode = filters.get('quality_mode', 'crf')
    if quality_mode == 'crf':
        crf = filters.get('crf', 18)
        cmd.extend(['-crf', str(crf)])
    elif quality_mode == 'bitrate':
        target_bitrate = filters.get('target_bitrate', 5000)
        cmd.extend(['-b:v', f'{target_bitrate}k'])

    # pixel format
    pix_fmt = filters.get('pix_fmt', 'yuv422p')
    cmd.extend(['-pix_fmt', pix_fmt])

    # aspect ratio
    aspect = filters.get('aspect', '4:3')
    if aspect != 'auto':
        cmd.extend(['-aspect', aspect])

    cmd.append(output_path)

    try:
        process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        job_id = f"{date}_{time_slot}_{filename}_{len(PROCESSING_JOBS)}"
        PROCESSING_JOBS[job_id] = {
            'process': process,
            'input': filename,
            'output': output_filename,
            'date': date,
            'time': time_slot,
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
            'error': stderr[-1000:]
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
