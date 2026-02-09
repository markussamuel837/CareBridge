#!/usr/bin/env python3
# ============================================================
# CareBridge Raspberry Pi Control Panel (Voice + MP3 Ringtone)
# Buttons (BCM):
#   GPIO 5  → Send SMS
#   GPIO 6  → Make Call
#   GPIO 13 → Join Jitsi Meeting
#   GPIO 21 → End Call / End Meeting
#   GPIO 26 → Answer Incoming Call
#
# Audio routing (confirmed):
#   Pulse Sink  (USB speaker): alsa_output.usb-GeneralPlus_USB_Audio_Device-00.analog-stereo
#   Pulse Source (ICS mic)   : alsa_input.platform-soc_sound.stereo-fallback
#   ALSA Playback: card 3, device 0 (USB)
#   ALSA Capture : card 2, device 0 (ICS43434 via voiceHAT driver)
# ============================================================

import os
import re
import time
import glob
import serial
import threading
import subprocess
import pathlib
from shutil import which

import RPi.GPIO as GPIO

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ----------------------------------------------------------------------
# ⚙️ GPIO SETUP
# ----------------------------------------------------------------------
PIN_SMS    = 5
PIN_CALL   = 6
PIN_CONF   = 13
PIN_EXIT   = 21
PIN_ANSWER = 26
SELECT_PIN = 12

GPIO.setmode(GPIO.BCM)
GPIO.setup(SELECT_PIN, GPIO.OUT, initial=GPIO.LOW)
for pin in [PIN_SMS, PIN_CALL, PIN_CONF, PIN_EXIT, PIN_ANSWER]:
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

active_call = False
ser = None

# ----------------------------------------------------------------------
# 🗣️ VOICE FEEDBACK
# ----------------------------------------------------------------------
def speak(message: str):
    print(f"🔊 {message}")
    safe = message.replace("'", " ")
    os.system(f"espeak -ven+f3 -s150 '{safe}' >/dev/null 2>&1")

# ----------------------------------------------------------------------
# 🔔 RINGTONE
# ----------------------------------------------------------------------
def play_ringtone():
    try:
        return subprocess.Popen(
            ["mpg123", "-q", "--loop", "-1", "/home/pi/ringtone.mp3"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except FileNotFoundError:
        speak("Ringtone file not found")
        return None

def stop_ringtone(proc):
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()

# ----------------------------------------------------------------------
# 🔊 AUDIO (fast + stable)
# ----------------------------------------------------------------------
PULSE_SINK_USB   = "alsa_output.usb-GeneralPlus_USB_Audio_Device-00.analog-stereo"
PULSE_SOURCE_ICS = "alsa_input.platform-soc_sound.stereo-fallback"

def run_cmd(cmd):
    try:
        subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

def ensure_alsa_defaults_for_jitsi():
    # ALSA fallback routing (Chrome/WebRTC will often follow this if Pulse is unavailable)
    asoundrc = pathlib.Path.home() / ".asoundrc"
    asoundrc.write_text(
        'pcm.!default {\n'
        '  type asym\n'
        '  playback.pcm "plughw:3,0"\n'  # USB speaker
        '  capture.pcm  "plughw:2,0"\n'  # ICS mic
        '}\n'
    )

_PACTL_OK = None
_PACTL_OK_TS = 0.0

def pactl_connected(ttl_sec: int = 30) -> bool:
    """Cached check so we don't slow the Pi down."""
    global _PACTL_OK, _PACTL_OK_TS
    now = time.time()
    if _PACTL_OK is not None and (now - _PACTL_OK_TS) < ttl_sec:
        return _PACTL_OK

    if not which("pactl"):
        _PACTL_OK = False
        _PACTL_OK_TS = now
        return False

    try:
        subprocess.check_output(["pactl", "info"], text=True, stderr=subprocess.STDOUT)
        _PACTL_OK = True
    except Exception:
        _PACTL_OK = False

    _PACTL_OK_TS = now
    return _PACTL_OK

def set_max_volume_unmute():
    # PipeWire/Pulse route (only if connected)
    if pactl_connected():
        run_cmd(["pactl", "set-default-sink", PULSE_SINK_USB])
        run_cmd(["pactl", "set-default-source", PULSE_SOURCE_ICS])

        run_cmd(["pactl", "set-sink-mute", PULSE_SINK_USB, "0"])
        run_cmd(["pactl", "set-sink-volume", PULSE_SINK_USB, "100%"])
        run_cmd(["pactl", "set-source-mute", PULSE_SOURCE_ICS, "0"])
        run_cmd(["pactl", "set-source-volume", PULSE_SOURCE_ICS, "100%"])

    # ALSA fallback volume (USB card 3)
    run_cmd(["amixer", "-c", "3", "sset", "Master", "100%", "unmute"])
    run_cmd(["amixer", "-c", "3", "sset", "PCM", "100%", "unmute"])

# ----------------------------------------------------------------------
# 🎥 JITSI JOIN HELPERS
# ----------------------------------------------------------------------
def click_join_strong(driver, timeout=40) -> bool:
    """Strong join click: tries CSS/XPath + scroll + JS click + ENTER fallback."""
    css_selectors = [
        "button[data-testid='prejoin.joinMeeting']",
        "button[data-testid*='join']",
        "button[type='submit']",
    ]
    xpath_selectors = [
        "//button[normalize-space()='Join']",
        "//button[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'join meeting')]",
        "//button[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'join')]",
        "//div[@role='button' and contains(.,'Join')]",
    ]

    end = time.time() + timeout
    while time.time() < end:
        for sel in css_selectors:
            try:
                btn = WebDriverWait(driver, 2).until(EC.element_to_be_clickable((By.CSS_SELECTOR, sel)))
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                time.sleep(0.2)
                driver.execute_script("arguments[0].click();", btn)
                print(f"🟢 Clicked Join (CSS): {sel}")
                return True
            except Exception:
                pass

        for sel in xpath_selectors:
            try:
                btn = WebDriverWait(driver, 2).until(EC.element_to_be_clickable((By.XPATH, sel)))
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                time.sleep(0.2)
                driver.execute_script("arguments[0].click();", btn)
                print(f"🟢 Clicked Join (XPATH): {sel}")
                return True
            except Exception:
                pass

        # ENTER fallback
        try:
            driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ENTER)
        except Exception:
            pass

        time.sleep(0.5)

    print("⚠️ Join button not found/clickable.")
    return False

def dismiss_common_popups(driver):
    """Best-effort: closes cookie/consent popups that block Join on some builds."""
    candidates = [
        # Common consent buttons
        (By.XPATH, "//button[contains(.,'Accept')]"),
        (By.XPATH, "//button[contains(.,'I agree')]"),
        (By.XPATH, "//button[contains(.,'Agree')]"),
        (By.XPATH, "//button[contains(.,'OK')]"),
        (By.XPATH, "//button[contains(.,'Got it')]"),
        (By.XPATH, "//button[contains(.,'Continue')]"),
        # Some dialogs use div role=button
        (By.XPATH, "//div[@role='button' and contains(.,'Accept')]"),
        (By.XPATH, "//div[@role='button' and contains(.,'Continue')]"),
    ]
    for by, sel in candidates:
        try:
            btn = WebDriverWait(driver, 1).until(EC.element_to_be_clickable((by, sel)))
            driver.execute_script("arguments[0].click();", btn)
            time.sleep(0.2)
        except Exception:
            pass

# ----------------------------------------------------------------------
# 📟 MODEM: AUTO-DETECT SERIAL PORT (NO CRASH)
# ----------------------------------------------------------------------
def find_modem_port():
    candidates = ["/dev/serial0", "/dev/ttyAMA0", "/dev/ttyS0"]
    candidates += sorted(glob.glob("/dev/ttyUSB*")) + sorted(glob.glob("/dev/ttyACM*"))
    for dev in candidates:
        if os.path.exists(dev):
            return dev
    return None

def open_modem():
    global ser
    port = find_modem_port()
    if not port:
        print("⚠️ No serial modem device found.")
        speak("Modem not found")
        ser = None
        return False
    try:
        ser = serial.Serial(port, baudrate=9600, timeout=1)
        print(f"✅ Modem serial opened on {port}")
        return True
    except Exception as e:
        print(f"⚠️ Could not open modem port {port}: {e}")
        speak("Modem port error")
        ser = None
        return False

def send_at(cmd, delay=1):
    if ser is None:
        return ""
    ser.write((cmd + "\r").encode())
    time.sleep(delay)
    resp = ser.read_all().decode(errors="ignore")
    print(f">>> {cmd}\n{resp.strip()}\n")
    return resp

def modem_init():
    if ser is None and not open_modem():
        return False
    print("📡 Initialising SIM800L modem …")
    speak("Initializing modem")
    for c in ["AT", "ATE0", "AT+CMEE=2", "AT+CSQ", "AT+CREG?",
              "AT+CLIP=1", "AT+CLVL=100", "AT+CMIC=0,15", "AT+CHFA=0"]:
        send_at(c, 0.5)
    return True

# ----------------------------------------------------------------------
# 📱 SMS
# ----------------------------------------------------------------------
def send_sms():
    if not modem_init():
        speak("Modem not available")
        return
    number = "+2348143042627"
    msg = "Hello from Raspberry Pi button!"
    speak("Sending message")
    print("📤 Sending SMS …")
    send_at("AT+CMGF=1")
    send_at('AT+CSCS="GSM"')
    ser.write((f'AT+CMGS="{number}"\r').encode())
    time.sleep(1)
    ser.write((msg + "\x1A").encode())
    time.sleep(5)
    print(ser.read_all().decode(errors="ignore"))
    speak("Message sent")

# ----------------------------------------------------------------------
# 📞 CALL MANAGEMENT
# ----------------------------------------------------------------------
def handle_active_call():
    global active_call
    speak("Call in progress")
    GPIO.output(SELECT_PIN, GPIO.HIGH)
    try:
        while active_call:
            if ser and ser.in_waiting:
                line = ser.readline().decode(errors="ignore").strip()
                if line:
                    print(line)
                    if any(k in line for k in ["NO CARRIER", "BUSY", "ERROR"]):
                        speak("Call ended")
                        active_call = False
                        break

            if GPIO.input(PIN_EXIT) == GPIO.LOW:
                speak("Ending call")
                send_at("ATH", 1)
                active_call = False
                GPIO.output(SELECT_PIN, GPIO.LOW)
                break

            time.sleep(0.2)
    finally:
        active_call = False
        GPIO.output(SELECT_PIN, GPIO.LOW)
        speak("Call finished")

def monitor_incoming_calls():
    global active_call
    ringtone_proc = None
    open_modem()

    while True:
        try:
            if ser and ser.in_waiting:
                line = ser.readline().decode(errors="ignore").strip()
                if not line:
                    time.sleep(0.05)
                    continue

                if "RING" in line:
                    speak("Incoming call")
                    if ringtone_proc is None or ringtone_proc.poll() is not None:
                        ringtone_proc = play_ringtone()
                        GPIO.output(SELECT_PIN, GPIO.HIGH)

                elif "+CLIP:" in line:
                    match = re.search(r'\+CLIP:\s*\"(\+?\d+)\"', line)
                    if match:
                        caller = match.group(1)
                        speak("Incoming call from " + " ".join(list(caller)))
                        GPIO.output(SELECT_PIN, GPIO.HIGH)

                if "RING" in line or "+CLIP:" in line:
                    while True:
                        if GPIO.input(PIN_ANSWER) == GPIO.LOW:
                            stop_ringtone(ringtone_proc)
                            ringtone_proc = None
                            speak("Answering call")
                            send_at("ATA", 1)
                            active_call = True
                            handle_active_call()
                            break
                        elif GPIO.input(PIN_EXIT) == GPIO.LOW:
                            stop_ringtone(ringtone_proc)
                            ringtone_proc = None
                            speak("Call rejected")
                            send_at("ATH", 1)
                            break
                        time.sleep(0.1)

            time.sleep(0.1)
        except Exception:
            time.sleep(0.5)

def make_call():
    global active_call
    if not modem_init():
        speak("Modem not available")
        return
    number = "+2348143042627"
    speak("Dialing number")
    send_at(f"ATD{number};", 3)
    active_call = True
    handle_active_call()

# ----------------------------------------------------------------------
# 🎥 JITSI JOIN
# ----------------------------------------------------------------------
def join_meeting_instance(meeting_url, name):
    ensure_alsa_defaults_for_jitsi()
    set_max_volume_unmute()

    opts = Options()
    opts.binary_location = "/usr/bin/chromium-browser"
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    for a in [
        "--start-fullscreen",
        "--disable-infobars",
        "--disable-extensions",
        "--noerrdialogs",
        "--autoplay-policy=no-user-gesture-required",
        "--use-fake-ui-for-media-stream",
        "--no-sandbox",
    ]:
        opts.add_argument(a)

    driver = webdriver.Chrome(
        service=Service(which("chromedriver") or "/usr/bin/chromedriver"),
        options=opts
    )

    try:
        driver.get(meeting_url)
        time.sleep(8)

        # Some builds show popups that block Join
        dismiss_common_popups(driver)

        # Enter name
        try:
            for sel in [
                "//input[contains(@placeholder,'name')]",
                "//input[@aria-label='Your name']",
                "//input[@name='userName']"
            ]:
                try:
                    box = WebDriverWait(driver, 3).until(
                        EC.presence_of_element_located((By.XPATH, sel))
                    )
                    box.clear()
                    box.send_keys(name)
                    break
                except TimeoutException:
                    continue
        except Exception:
            pass

        dismiss_common_popups(driver)

        # Click Join
        joined = click_join_strong(driver, timeout=40)
        if not joined:
            speak("Join not clicked")
            print("⚠️ Join not clicked. (Possible popup or page change)")
        else:
            print("✅ Join clicked")
            speak("Conference joined")

        # Meeting loop (refresh audio every 20s)
        next_audio_fix = 0
        while GPIO.input(PIN_EXIT) == GPIO.HIGH:
            now = time.time()
            if now >= next_audio_fix:
                set_max_volume_unmute()
                next_audio_fix = now + 20
            time.sleep(0.2)

    finally:
        try:
            driver.quit()
        except Exception:
            pass
        speak("Conference ended")

def join_meeting():
    url = "https://meet.jit.si/FollowingWavesSupposeAcross"
    join_meeting_instance(url, "CareBridge")

# ----------------------------------------------------------------------
# 🕹️ MAIN LOOP
# ----------------------------------------------------------------------
print("🚀 Ready. Press:")
print(f"  • GPIO {PIN_SMS} → Send SMS")
print(f"  • GPIO {PIN_CALL} → Make Call")
print(f"  • GPIO {PIN_ANSWER} → Answer Incoming Call")
print(f"  • GPIO {PIN_CONF} → Join Conference")
print(f"  • GPIO {PIN_EXIT} → End Call / End Meeting")
speak("System ready")

threading.Thread(target=monitor_incoming_calls, daemon=True).start()

try:
    while True:
        if GPIO.input(PIN_SMS) == GPIO.LOW:
            send_sms()
            time.sleep(1)

        elif GPIO.input(PIN_CALL) == GPIO.LOW:
            make_call()
            time.sleep(1)

        elif GPIO.input(PIN_CONF) == GPIO.LOW:
            join_meeting()
            time.sleep(1)

        time.sleep(0.1)

except KeyboardInterrupt:
    speak("Shutting down system")

finally:
    GPIO.cleanup()
    try:
        if ser:
            ser.close()
    except Exception:
        pass
    speak("System stopped")
