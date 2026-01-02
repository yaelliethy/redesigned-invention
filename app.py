import os
import time
import random
import string
import json
import requests
from datetime import datetime, timedelta
from flask import Flask, Response
from bs4 import BeautifulSoup
from faker import Faker
import re
import threading

# --- Configuration ---
BASE_URL = "https://tv.net.pk"
AJAX_URL = f"{BASE_URL}/wp-admin/admin-ajax.php"
ACCOUNT_URL = f"{BASE_URL}/my-account/"

CREDENTIALS_FILE = "credentials.txt"
M3U_CACHE_FILE = "live_cache.m3u"
M3U_CACHE_TIME_FILE = "live_cache.time"
TRIAL_VALID_HOURS = 20
CACHE_MAX_AGE = 20 * 3600  # 20 hours in seconds

# Background state
init_in_progress = False
init_error = None

fake = Faker()
app = Flask(__name__)

# Lock for thread safety (basic)
init_lock = threading.Lock()

# --- Helper: LIVE-only filter ---
def make_live_only_m3u(input_path: str, output_path: str) -> None:
    with open(input_path, "r", encoding="utf-8", errors="ignore") as fin, \
         open(output_path, "w", encoding="utf-8") as fout:

        last_extinf = None
        for raw_line in fin:
            line = raw_line.strip()
            if line.startswith("#EXTM3U"):
                fout.write(line + "\n")
                continue
            if line.startswith("#EXTINF"):
                last_extinf = line
                continue
            if "/live/" in line and "/movie/" not in line and "/series/" not in line:
                if last_extinf:
                    fout.write(last_extinf + "\n")
                    last_extinf = None
                fout.write(line + "\n")
            else:
                last_extinf = None
# --- Auth & Credential Helpers (from your original code) ---
def random_suffix(k=4):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=k))

def generate_email(first, last):
    first = first.lower()
    last = last.lower()
    suffix = random_suffix()
    formats = [
        f"{first}.{last}{suffix}@gmail.com",
        f"{first}{last}{suffix}@gmail.com",
        f"{first}-{last}{suffix}@gmail.com",
        f"{first}_{last}{suffix}@gmail.com",
        f"{first[0]}{last}{suffix}@gmail.com",
    ]
    return random.choice(formats)

def generate_identity():
    first = fake.first_name()
    last = fake.last_name()
    return {
        "first": first,
        "last": last,
        "email": generate_email(first, last),
        "password": "Pa$$w0rd!"
    }

def register(session, identity):
    boundary = "----geckoformboundary" + random_suffix(24)

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64)",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": BASE_URL,
        "Referer": f"{BASE_URL}/my-account/",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="xoo_el_reg_email"\r\n\r\n{identity["email"]}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="xoo_el_reg_pass"\r\n\r\n{identity["password"]}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="xoo_el_reg_pass_again"\r\n\r\n{identity["password"]}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="xoo_el_reg_fname"\r\n\r\n{identity["first"]}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="xoo_el_reg_lname"\r\n\r\n{identity["last"]}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="xoo_el_reg_terms"\r\n\r\nyes\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="_xoo_el_form"\r\n\r\nregister\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="xoo_el_redirect"\r\n\r\n/my-account/\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="action"\r\n\r\nxoo_el_form_action\r\n'
        f"--{boundary}--\r\n"
    )

    r = session.post(AJAX_URL, headers=headers, data=body, timeout=15)
    r.raise_for_status()
    return r.json()

def get_nonce(session):
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64)",
        "Referer": f"{BASE_URL}/free-iptv/",
    }
    response = session.get(f"{BASE_URL}/free-iptv/", timeout=10, headers=headers)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    scripts = soup.find_all("script")
    nonce = None
    for script in scripts:
        if script.string and "primeStreamApiData" in script.string:
            match = re.search(r"var\s+primeStreamApiData\s*=\s*(\{.*?\});", script.string, re.DOTALL)
            if match:
                js_object = match.group(1)
                js_object = js_object.replace("'", '"')

                data = json.loads(js_object)
                nonce = data.get("nonce")
                break
    if nonce:
        return nonce
    else:
        return None
def generate_trial(session, nonce):
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64)",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": BASE_URL,
        "Referer": f"{BASE_URL}/free-iptv/",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }

    data = {
        "action": "generate_24hour_data",
        "nonce": nonce,
    }

    r = session.post(AJAX_URL, headers=headers, data=data, timeout=15)
    r.raise_for_status()
    return r.json()


def fetch_credentials(session):
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64)",
        "Referer": f"{BASE_URL}/free-iptv/",
    }

    r = session.get(ACCOUNT_URL, headers=headers, timeout=15)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")

    return {
        "username": soup.select_one(".account-username").get_text(strip=True),
        "password": soup.select_one(".account-password").get_text(strip=True),
    }

def load_latest_credentials():
    if not os.path.exists(CREDENTIALS_FILE):
        return None
    with open(CREDENTIALS_FILE, "r") as f:
        lines = f.readlines()
    if len(lines) < 6:
        return None
    try:
        time_str = lines[-6].strip().split("Time: ")[1]
        cred_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        if datetime.now() - cred_time < timedelta(hours=TRIAL_VALID_HOURS):
            email = lines[-5].split("Email: ")[1].strip()
            username = lines[-4].split("Username: ")[1].strip()
            password = lines[-3].split("Password: ")[1].strip()
            return {"email": email, "username": username, "password": password}
    except Exception:
        pass
    return None

def save_credentials(identity, creds):
    with open(CREDENTIALS_FILE, "a") as f:
        f.write(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Email: {identity['email']}\n")
        f.write(f"Username: {creds['username']}\n")
        f.write(f"Password: {creds['password']}\n")
        f.write("Server:  http://tvsystem.my:80\n")
        f.write("-" * 40 + "\n")

def _background_init():
    global init_in_progress, init_error
    try:
        ensure_fresh_m3u()
        init_error = None
    except Exception as e:
        init_error = str(e)
    finally:
        init_in_progress = False

def ensure_fresh_m3u():
    """Same as before — downloads and filters M3U."""
    if os.path.exists(M3U_CACHE_TIME_FILE):
        with open(M3U_CACHE_TIME_FILE, "r") as f:
            try:
                cached_time = float(f.read().strip())
                if time.time() - cached_time < CACHE_MAX_AGE:
                    return
            except ValueError:
                pass

    creds = load_latest_credentials()
    if not creds:
        identity = generate_identity()
        session = requests.Session()
        time.sleep(random.uniform(1.2, 2.2))

        reg = register(session, identity)
        if reg.get("error") != 0:
            raise RuntimeError("Registration failed")

        nonce = get_nonce(session)
        if not nonce:
            raise RuntimeError("Nonce extraction failed")

        trial = generate_trial(session, nonce)
        if not trial.get("success"):
            raise RuntimeError("Trial generation failed")

        creds = fetch_credentials(session)
        save_credentials(identity, creds)

    full_url = f"http://tvsystem.my:80/get.php?username={creds['username']}&password={creds['password']}&type=m3u_plus&output=ts"
    temp_raw = "temp_full.m3u"
    
    try:
        with requests.get(full_url, timeout=30, stream=True) as response:
            response.raise_for_status()
            with open(temp_raw, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
        make_live_only_m3u(temp_raw, M3U_CACHE_FILE)
        with open(M3U_CACHE_TIME_FILE, "w") as f:
            f.write(str(time.time()))
    finally:
        if os.path.exists(temp_raw):
            os.remove(temp_raw)

# --- Flask Routes ---

@app.route("/init")
def init():
    global init_in_progress, init_error
    with init_lock:
        if init_in_progress:
            return {"status": "already running"}, 202
        if os.path.exists(M3U_CACHE_FILE):
            # Optional: check if still valid
            if os.path.exists(M3U_CACHE_TIME_FILE):
                try:
                    with open(M3U_CACHE_TIME_FILE) as f:
                        if time.time() - float(f.read()) < CACHE_MAX_AGE:
                            return {"status": "already cached and fresh"}, 200
                except:
                    pass
        # Start background job
        init_in_progress = True
        init_error = None
        thread = threading.Thread(target=_background_init)
        thread.daemon = True
        thread.start()
        return {"status": "initialization started in background"}, 202

@app.route("/live.m3u")
def serve_live_m3u():
    if not os.path.exists(M3U_CACHE_FILE):
        return "M3U not ready. Call /init first.", 404

    # Optional: check age
    if os.path.exists(M3U_CACHE_TIME_FILE):
        try:
            with open(M3U_CACHE_TIME_FILE, "r") as f:
                if time.time() - float(f.read()) >= CACHE_MAX_AGE:
                    # Optionally trigger background refresh (not required)
                    pass
        except:
            pass

    try:
        with open(M3U_CACHE_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        return Response(content, mimetype="application/x-mpegURL")
    except Exception as e:
        return f"Error reading M3U: {str(e)}", 500

@app.route("/health")
def health():
    ready = os.path.exists(M3U_CACHE_FILE)
    return {
        "status": "ok",
        "m3u_ready": ready,
        "init_in_progress": init_in_progress,
        "init_error": init_error
    }

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))