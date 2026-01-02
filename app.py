# app.py
import os
import time
import random
import string
import json
from datetime import datetime, timedelta

import requests
from flask import Flask, redirect, jsonify, request
from bs4 import BeautifulSoup
from faker import Faker
import re

# --- Configuration ---
BASE_URL = "https://tv.net.pk"
AJAX_URL = f"{BASE_URL}/wp-admin/admin-ajax.php"
ACCOUNT_URL = f"{BASE_URL}/my-account/"

CREDENTIALS_FILE = "credentials.txt"
TRIAL_VALID_HOURS = 20

fake = Faker()

app = Flask(__name__)

# --- Helper Functions (from your script) ---

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
            return {"email": email, "username": username, "password": password, "time": cred_time}
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

# --- Flask Route ---

@app.route("/get-m3u")
def get_m3u():
    # Optional: Add basic auth or IP restriction here in production
    creds = load_latest_credentials()
    if not creds:
        identity = generate_identity()
        session = requests.Session()
        time.sleep(random.uniform(1.2, 2.2))

        reg = register(session, identity)
        if reg.get("error") != 0:
            return jsonify({"error": "Registration failed"}), 500

        nonce = get_nonce(session)
        if not nonce:
            return jsonify({"error": "Nonce extraction failed"}), 500

        trial = generate_trial(session, nonce)
        if not trial.get("success"):
            return jsonify({"error": "Trial generation failed"}), 500

        creds = fetch_credentials(session)
        save_credentials(identity, creds)

    m3u_url = f"http://tvsystem.my:80/get.php?username={creds['username']}&password={creds['password']}&type=m3u_plus&output=ts"
    return redirect(m3u_url, code=302)

# Optional: Health check
@app.route("/health")
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)