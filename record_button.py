import subprocess
import datetime
import os
import time
from gpiozero import Button, LED
from signal import pause

# --- Configuration ---
BUTTON_PIN = 17
LED_PIN = 27
VIDEO_DEVICE = "/dev/video0"
AUDIO_DEVICE = "hw:2,0" 

# Directories
OUTPUT_DIR = os.path.expanduser("~/Videos")

button = Button(BUTTON_PIN, pull_up=True, hold_time=3)
led = LED(LED_PIN)

recording_process = None
current_recording_info = None

def get_time_directory():
    """Get or create directory for current date and time"""
    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H-%M")
    
    date_dir = os.path.join(OUTPUT_DIR, date_str)
    time_dir = os.path.join(date_dir, time_str)
    raw_dir = os.path.join(time_dir, "raw")
    processed_dir = os.path.join(time_dir, "processed")
    
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(processed_dir, exist_ok=True)
    
    return time_dir, raw_dir, processed_dir

def configure_device():
    """
    Configures the capture card before recording.
    """
    print("Configuring capture device...")
    try:
        # 1. Force NTSC Standard
        subprocess.run(["/usr/bin/v4l2-ctl", "-d", VIDEO_DEVICE, "-s", "ntsc"])
        time.sleep(0.3) # Allow firmware to settle
        
        # 2. Force Input 1 (S-Video)
        subprocess.run(["/usr/bin/v4l2-ctl", "-d", VIDEO_DEVICE, "-i", "1"])
        time.sleep(0.3) # Allow signal lock
        
    except Exception as e:
        print(f"Hardware setup warning: {e}")

def process_with_defaults(input_path, output_dir):
    """
    Process video with default settings:
    - Deinterlacing (bwdif)
    - High-pass filter @ 80Hz
    - Noise reduction (anlmdn)
    - Loudness normalization
    """
    filename = os.path.basename(input_path)
    base_name = filename.replace('.mp4', '')
    output_filename = f"{base_name}_default.mp4"
    output_path = os.path.join(output_dir, output_filename)
    
    print(f"Starting default processing: {output_path}")
    
    # Video filters: deinterlace only
    vf = "setfield=tff,bwdif=1"
    
    # Audio filters: highpass, noise reduction, normalization
    af = "highpass=f=80,anlmdn=s=0.0001,loudnorm"
    
    cmd = [
        "nice", "-n", "10",
        "/usr/bin/ffmpeg", "-y",
        "-i", input_path,
        "-vf", vf,
        "-af", af,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-aspect", "4:3",
        "-c:a", "aac",
        "-b:a", "192k",
        output_path
    ]
    
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def start_recording():
    global recording_process, current_recording_info
    
    # Run setup immediately before recording
    configure_device()
    
    # Get time-based directory structure
    time_dir, raw_dir, processed_dir = get_time_directory()
    
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"record_{timestamp}.mp4"
    filepath = os.path.join(raw_dir, filename)
    
    current_recording_info = {
        'filepath': filepath,
        'processed_dir': processed_dir,
        'time_dir': time_dir
    }
    
    print(f"Starting archival recording: {filepath}")

    cmd = [
        "/usr/bin/ffmpeg", "-y",
        "-f", "v4l2",
        "-input_format", "yuyv422",
        "-i", VIDEO_DEVICE,
        "-f", "alsa",
        "-i", AUDIO_DEVICE,
        "-c:v", "libx264",
        "-crf", "18",
        "-pix_fmt", "yuv422p",
        "-aspect", "4:3",
        "-preset", "superfast",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ac", "2",
        "-af", "aresample=async=1:min_hard_comp=0.100000:first_pts=0",
        filepath
    ]
    
    devnull = open(os.devnull, 'w')
    recording_process = subprocess.Popen(cmd, stdout=devnull, stderr=devnull)
    led.on()

def stop_recording():
    global recording_process, current_recording_info
    
    if recording_process:
        print("Stopping recording...")
        recording_process.terminate()
        try:
            recording_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            recording_process.kill()
        
        recording_process = None
        led.off()
        print("Recording stopped.")
        
        # Start automatic default processing
        if current_recording_info and os.path.exists(current_recording_info['filepath']):
            process_with_defaults(
                current_recording_info['filepath'],
                current_recording_info['processed_dir']
            )
        
        current_recording_info = None

def toggle_recording():
    if recording_process is None:
        start_recording()
    else:
        stop_recording()

def safe_shutdown():
    if recording_process:
        stop_recording()
    print("Shutting down...")
    led.blink(on_time=0.1, off_time=0.1, n=10)
    os.system("sudo shutdown -h now")

# --- Assignments ---
button.when_pressed = toggle_recording
button.when_held = safe_shutdown

print("System Ready. Videos organized by date/time in ~/Videos/")
print("Default processing (deinterlace + audio cleanup) applied automatically")
pause()
