# raspberry pi camcorder system

converts a raspberry pi + capture card + old camcorder into a tapeless recording system with wifi access.

## features

- **button-controlled recording**: physical button to start/stop recordings
- **automatic deinterlacing**: background processing of recorded footage
- **wifi access point**: creates its own wifi network for easy access
- **web interface**: browse, stream, and download recordings from any device
- **auto-updates**: automatically pulls code updates when ethernet is connected
- **easy deployment**: bootstrap script can rebuild entire system on fresh pi in minutes


## deployment (new pi or fresh install)

the fastest way to deploy this system is using the bootstrap script:

```bash
# on a fresh raspberry pi os installation
curl -sSL https://raw.githubusercontent.com/wolces/camcorder/main/bootstrap.sh | sudo bash
```

this will:
- install all required packages
- clone your git repository
- configure services
- setup wifi access point
- install auto-update system

after bootstrap completes, just reboot and you're ready!

see **bootstrap script setup** section below for first-time configuration.

## updating existing installation

if you already have the system installed and just want to update:

### automatic update (recommended)
1. make changes to code on your computer
2. commit and push to git
3. plug ethernet cable into pi
4. wait ~30 seconds - updates apply automatically!

### manual update
```bash
ssh camcorder@raspberrypi.local
cd /home/camcorder
git pull
sudo systemctl restart web_server.service
sudo systemctl restart wifi_ap.service
```

## bootstrap script setup (first time only)

before deploying to your first pi, you need to configure the bootstrap script:

1. **create a git repository**
   - create a new repository on github/gitlab
   - note the clone url

2. **edit bootstrap.sh**
   open `bootstrap.sh` and update these lines at the top:
   ```bash
   GIT_REPO="https://github.com/YOUR_USERNAME/camcorder.git"
   GIT_BRANCH="main"
   WIFI_SSID="Camcorder"
   WIFI_PASSWORD="recording"
   ```

3. **commit all files to repository**
   ```bash
   cd /home/camcorder
   git init
   git remote add origin https://github.com/YOUR_USERNAME/camcorder.git
   git add .
   git commit -m "initial commit"
   git push -u origin main
   ```

4. **test on your current pi** (optional but recommended)
   ```bash
   sudo bash bootstrap.sh
   sudo reboot
   ```

now the bootstrap script is ready to deploy to any fresh pi!

## deploying to a new pi

1. **flash raspberry pi os**
   - use raspberry pi imager
   - select "raspberry pi os lite (64-bit)" or full desktop version
   - enable ssh in settings (optional but recommended)
   - optionally configure wifi for initial access

2. **boot and run bootstrap**
   ```bash
   # ssh into the pi (or use monitor/keyboard)
   ssh pi@raspberrypi.local
   
   # run bootstrap
   curl -sSL https://raw.githubusercontent.com/YOUR_USERNAME/camcorder/main/bootstrap.sh | sudo bash
   
   # reboot
   sudo reboot
   ```

3. **done!** the new pi is identical to your original

## usage

### recording videos

1. **short press**: start/stop recording
2. **long press (3 seconds)**: shutdown pi safely

recordings are saved to `~/Videos/`:
- **original**: `record_YYYY-MM-DD_HH-MM-SS.mp4` (high quality, interlaced)
- **processed**: `~/Videos/deinterlaced/` (deinterlaced for modern displays)

### accessing videos via wifi

1. connect to wifi network:
   - **ssid**: `Camcorder`
   - **password**: `recording`

2. open browser to: `http://192.168.4.1:8080`

3. from the web interface you can:
   - view all recordings
   - stream videos directly
   - download to your device
   - delete unwanted files
   - see recording status and disk space

## configuration

### wifi settings

edit `hostapd.conf` to change:
- `ssid`: network name
- `wpa_passphrase`: password (minimum 8 characters)
- `channel`: wifi channel (1-11)

```bash
# after editing, restart wifi ap
sudo systemctl restart wifi_ap.service
```

### video/audio settings

if you need to adjust recording settings, edit `record_button.py`:
- `VIDEO_DEVICE`: usually `/dev/video0`
- `AUDIO_DEVICE`: check with `arecord -l` if you need to change
- video quality: change `-crf 16` (lower = better quality, 16-23 recommended)
- audio bitrate: change `-b:a 192k` (128k-320k)

### auto-update settings

edit `auto_update.py` to configure:
- `GIT_REMOTE`: remote name (default: "origin")
- `GIT_BRANCH`: branch name (default: "main")
- `CHECK_INTERVAL`: how often to check for ethernet (default: 10 seconds)

## file structure

```
/home/camcorder/
├── record_button.py          # main recording script
├── web_server.py             # flask web server
├── auto_update.py            # auto-update monitor
├── setup_wifi_ap.sh          # wifi access point setup
├── bootstrap.sh              # deploy to new pi script
├── install.sh                # installation script (called by bootstrap)
├── templates/
│   └── index.html            # web interface
├── hostapd.conf              # wifi ap configuration
├── dnsmasq.conf              # dhcp/dns configuration
├── recorder.service          # systemd: recording button
├── web_server.service        # systemd: web server
├── wifi_ap.service           # systemd: wifi access point
├── auto_update.service       # systemd: auto-update
├── requirements.txt          # python dependencies
└── .gitignore                # git ignore rules
```

## troubleshooting

### wifi access point not working

```bash
# check service status
sudo systemctl status wifi_ap.service

# check hostapd logs
sudo journalctl -u wifi_ap.service

# verify wlan0 has correct ip
ip addr show wlan0
# should show: inet 192.168.4.1/24
```

### web server not accessible

```bash
# check service status
sudo systemctl status web_server.service

# check if running
sudo netstat -tlnp | grep 8080

# check logs
sudo journalctl -u web_server.service
```

### recording not working

```bash
# check service status
sudo systemctl status recorder.service

# verify video device
v4l2-ctl --list-devices
v4l2-ctl -d /dev/video0 --all

# check logs
sudo journalctl -u recorder.service
```

### auto-update not working

```bash
# check service status
sudo systemctl status auto_update.service

# verify ethernet connection
ip addr show eth0

# check git remote
cd /home/camcorder
git remote -v
git fetch origin

# check logs
sudo journalctl -u auto_update.service
```

### bootstrap script fails

```bash
# check internet connectivity
ping -c 3 google.com

# verify git repository is accessible
git ls-remote https://github.com/YOUR_USERNAME/camcorder.git

# run bootstrap with verbose output
sudo bash -x bootstrap.sh
```

## technical details

### video settings
- **codec**: h.264 (libx264)
- **pixel format**: yuv422p 
- **crf**: 16
- **audio**: aac 192kbps stereo

### deinterlacing
- **method**: bwdif (bob weaver deinterlacing filter)
- **field order**: top field first (standard for ntsc)
- **output**: 60fps progressive

### network
- **wifi range**: 192.168.4.2 - 192.168.4.20
- **gateway**: 192.168.4.1
- **dns**: handled by dnsmasq on pi

## development

### making changes

1. edit files on your development machine
2. commit and push to git repository
3. plug ethernet into pi
4. updates apply automatically

### testing locally

```bash
# test web server
python3 web_server.py

# test wifi setup (requires root)
sudo bash setup_wifi_ap.sh

# test recording script
python3 record_button.py
```

### viewing logs

```bash
# all services
sudo journalctl -f

# specific service
sudo journalctl -u recorder.service -f
sudo journalctl -u web_server.service -f
sudo journalctl -u wifi_ap.service -f
sudo journalctl -u auto_update.service -f
```

## security notes

- wifi password is stored in plain text in `hostapd.conf`
- web server has no authentication (assumes trusted network)
- sudo permissions required for auto-update service restarts

