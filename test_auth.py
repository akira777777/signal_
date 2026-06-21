import urllib.request
import urllib.error
import json
import time
import sys

base = "http://127.0.0.1:8788"
env_text = open("api-signal/.env").read()
web_pass = [l.split("=", 1)[1].strip() for l in env_text.splitlines() if l.startswith("TELEGRAM_WEB_PASSWORD=")][0]

login_data = json.dumps({"password": web_pass}).encode()
req = urllib.request.Request(
    base + "/api/login",
    data=login_data,
    headers={"Content-Type": "application/json", "Origin": "http://127.0.0.1:8788"},
)
resp = urllib.request.urlopen(req)
cookie = resp.headers.get("Set-Cookie", "")
session = cookie.split("telegram_session=")[1].split(";")[0] if "telegram_session=" in cookie else ""
print("Web login OK", flush=True)

# First /api/status
t0 = time.time()
req2 = urllib.request.Request(base + "/api/status", headers={"Cookie": f"telegram_session={session}"})
resp2 = urllib.request.urlopen(req2)
data = json.loads(resp2.read())
elapsed1 = time.time() - t0
chats = len(data.get("chats", []))
authorized = data.get("authorized")
print(f"First /api/status: {elapsed1:.1f}s, authorized={authorized}, chats={chats}", flush=True)

# Second /api/status (cached)
t1 = time.time()
req3 = urllib.request.Request(base + "/api/status", headers={"Cookie": f"telegram_session={session}"})
resp3 = urllib.request.urlopen(req3)
data2 = json.loads(resp3.read())
elapsed2 = time.time() - t1
print(f"Second /api/status (cached): {elapsed2:.3f}s", flush=True)

# Auth request-code
t2 = time.time()
req4 = urllib.request.Request(
    base + "/api/auth/request-code",
    data=b"{}",
    headers={
        "Content-Type": "application/json",
        "Origin": "http://127.0.0.1:8788",
        "Cookie": f"telegram_session={session}",
    },
)
try:
    resp4 = urllib.request.urlopen(req4)
    result = json.loads(resp4.read())
    elapsed3 = time.time() - t2
    print(f"Auth request-code: {elapsed3:.1f}s, result={result}", flush=True)
except urllib.error.HTTPError as e:
    elapsed3 = time.time() - t2
    print(f"Auth request-code ERROR {e.code} in {elapsed3:.1f}s: {e.read().decode()}", flush=True)
