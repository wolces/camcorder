#!/usr/bin/env python3
"""
auto-update system for camcorder
monitors for ethernet connection and pulls updates from git
"""

import subprocess
import time
import os
import sys
from pathlib import Path

# configuration
REPO_DIR = "/home/camcorder"
GIT_REMOTE = "origin"
GIT_BRANCH = "main"
CHECK_INTERVAL = 10  # seconds
UPDATE_FLAG = "/tmp/camcorder_updating"

def is_ethernet_connected():
    """check if eth0 has an ip address"""
    try:
        result = subprocess.run(['ip', 'addr', 'show', 'eth0'], 
                              capture_output=True, text=True, timeout=5)
        # look for "inet " which indicates an ipv4 address
        return 'inet ' in result.stdout and 'state UP' in result.stdout
    except:
        return False

def is_recording():
    """check if currently recording"""
    try:
        result = subprocess.run(['pgrep', '-f', 'ffmpeg.*video0'], 
                              capture_output=True, text=True, timeout=5)
        return bool(result.stdout.strip())
    except:
        return False

def git_fetch():
    """fetch latest from remote"""
    try:
        result = subprocess.run(['git', 'fetch', GIT_REMOTE], 
                              cwd=REPO_DIR, 
                              capture_output=True, 
                              text=True, 
                              timeout=30)
        return result.returncode == 0
    except Exception as e:
        print(f"git fetch failed: {e}")
        return False

def git_has_updates():
    """check if remote has new commits"""
    try:
        # get local commit hash
        local = subprocess.run(['git', 'rev-parse', 'HEAD'], 
                             cwd=REPO_DIR, 
                             capture_output=True, 
                             text=True, 
                             timeout=5)
        
        # get remote commit hash
        remote = subprocess.run(['git', 'rev-parse', f'{GIT_REMOTE}/{GIT_BRANCH}'], 
                              cwd=REPO_DIR, 
                              capture_output=True, 
                              text=True, 
                              timeout=5)
        
        return local.stdout.strip() != remote.stdout.strip()
    except Exception as e:
        print(f"failed to check for updates: {e}")
        return False

def apply_update():
    """pull latest code and restart services"""
    try:
        # create update flag
        Path(UPDATE_FLAG).touch()
        
        print("applying update...")
        
        # pull latest
        result = subprocess.run(['git', 'pull', GIT_REMOTE, GIT_BRANCH], 
                              cwd=REPO_DIR, 
                              capture_output=True, 
                              text=True, 
                              timeout=30)
        
        if result.returncode != 0:
            print(f"git pull failed: {result.stderr}")
            return False
        
        print("update pulled successfully")
        
        # make scripts executable
        subprocess.run(['chmod', '+x', 
                       '/home/camcorder/setup_wifi_ap.sh',
                       '/home/camcorder/auto_update.py'], 
                      timeout=5)
        
        # copy service files if they changed
        service_files = [
            'recorder.service',
            'web_server.service', 
            'wifi_ap.service',
            'auto_update.service'
        ]
        
        for service in service_files:
            src = f'/home/camcorder/{service}'
            dst = f'/etc/systemd/system/{service}'
            if os.path.exists(src):
                subprocess.run(['sudo', 'cp', src, dst], timeout=5)
        
        # reload systemd
        subprocess.run(['sudo', 'systemctl', 'daemon-reload'], timeout=10)
        
        # restart services (but not recorder to avoid interrupting recording)
        subprocess.run(['sudo', 'systemctl', 'restart', 'web_server.service'], timeout=10)
        subprocess.run(['sudo', 'systemctl', 'restart', 'wifi_ap.service'], timeout=10)
        
        print("services restarted")
        
        # remove update flag
        if os.path.exists(UPDATE_FLAG):
            os.remove(UPDATE_FLAG)
        
        return True
        
    except Exception as e:
        print(f"update failed: {e}")
        if os.path.exists(UPDATE_FLAG):
            os.remove(UPDATE_FLAG)
        return False

def main():
    print("auto-update monitor started")
    print(f"monitoring eth0 for connection...")
    print(f"repo: {REPO_DIR}")
    print(f"remote: {GIT_REMOTE}/{GIT_BRANCH}")
    
    last_ethernet_state = False
    
    while True:
        try:
            ethernet_connected = is_ethernet_connected()
            
            # ethernet just connected
            if ethernet_connected and not last_ethernet_state:
                print("ethernet connected, checking for updates...")
                
                # don't update if recording
                if is_recording():
                    print("recording in progress, skipping update")
                else:
                    if git_fetch():
                        if git_has_updates():
                            print("updates available, applying...")
                            if apply_update():
                                print("update complete!")
                            else:
                                print("update failed")
                        else:
                            print("already up to date")
                    else:
                        print("failed to fetch from remote")
            
            last_ethernet_state = ethernet_connected
            
        except Exception as e:
            print(f"error in main loop: {e}")
        
        time.sleep(CHECK_INTERVAL)

if __name__ == '__main__':
    main()
