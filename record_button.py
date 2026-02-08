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
DEINTERLACED_DIR = os.path.join(OUTPUT_DIR, "deinterlaced")

# Ensure directories exist
os.makedirs(DEINTERLACED_DIR, exist_ok=True)

button = Button(BUTTON_PIN, pull_up=True, hold_time=3)
led = LED(LED_PIN)

recording_process = None
current_recording_filename = None

def configure_device():
    """
    Configures the capture card before recording.
    """
    print("Configuring capture device...")
    try:
        # 1. Force NTSC Standard
        subprocess.run(["/usr/bin/v4l2-ctl", "-d", VIDEO_DEVICE, "-s", "ntsc"])
        time.sleep(0.5) # Allow firmware to settle
        
        # 2. Force Input 1 (S-Video)
        subprocess.run(["/usr/bin/v4l2-ctl", "-d", VIDEO_DEVICE, "-i", "1"])
        time.sleep(0.5) # Allow signal lock
        
    except Exception as e:
        print(f"Hardware setup warning: {e}")

def transcode_background(input_path):
    """
    Launches a detached FFmpeg process to deinterlace the video.
    """
    filename = os.path.basename(input_path)
    output_path = os.path.join(DEINTERLACED_DIR, filename)
    
    print(f"Queueing background transcode: {output_path}")
    
    cmd = [
        "nice", "-n", "10",
        "/usr/bin/ffmpeg", "-y",
        "-i", input_path,
        "-vf", "setfield=tff,bwdif=1", 
        "-c:v", "libx264",
        "-preset", "superfast",
        "-crf", "23",
        "-aspect", "4:3",
        "-c:a", "copy",
        output_path
    ]
    
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def start_recording():
    global recording_process, current_recording_filename
    
    # Run setup immediately before recording
    configure_device()
    
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    current_recording_filename = os.path.join(OUTPUT_DIR, f"record_{timestamp}.mp4")
    
    print(f"Starting archival recording: {current_recording_filename}")

    # The "Master" Archival Command
    # Preserves interlacing for future QTGMC restoration
    cmd = [
        "/usr/bin/ffmpeg", "-y",
        "-f", "v4l2",
        "-input_format", "yuyv422",
        "-i", VIDEO_DEVICE,
        "-f", "alsa",
        "-i", AUDIO_DEVICE,
        "-c:v", "libx264",
        "-crf", "16",
        "-pix_fmt", "yuv422p",
        "-aspect", "4:3",
        "-preset", "superfast",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ac", "2",
        "-af", "aresample=async=1:min_hard_comp=0.100000:first_pts=0",
        current_recording_filename
    ]
    
    devnull = open(os.devnull, 'w')
    recording_process = subprocess.Popen(cmd, stdout=devnull, stderr=devnull)
    led.on()

def stop_recording():
    global recording_process, current_recording_filename
    
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
        
        # Trigger the async deinterlace
        if current_recording_filename and os.path.exists(current_recording_filename):
            transcode_background(current_recording_filename)
        
        current_recording_filename = None

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

print("System Ready. Saving masters to ~/Videos and copies to ~/Videos/deinterlaced")
pause()
