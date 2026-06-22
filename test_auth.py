import urllib.request
import urllib.error
import json
import time

base = "http://127.0.0.1:8787"
env_text = open("api-signal/.env").read()
web_pass = [l.split("=", 1)[1].strip() for l in env_text.splitlines() if l.startswith("SIGNAL_WEB_PASSWORD=")][0]

login_data = json.dumps({"password": web_pass}).encode()
req = urllib.request.Request(
    base + "/api/login",
    data=login_data,
    headers={"Content-Type": "application/json", "Origin": "http://127.0.0.1:8787"},
)
resp = urllib.request.urlopen(req)
cookie = resp.headers.get("Set-Cookie", "")
session = cookie.split("signal_session=")[1].split(";")[0] if "signal_session=" in cookie else ""
print("Web login OK", flush=True)

# First /api/status
t0 = time.time()
req2 = urllib.request.Request(base + "/api/status", headers={"Cookie": f"signal_session={session}"})
resp2 = urllib.request.urlopen(req2)
data = json.loads(resp2.read())
elapsed1 = time.time() - t0
groups = len(data.get("groups", []))
connected = data.get("connected")
print(f"First /api/status: {elapsed1:.1f}s, connected={connected}, groups={groups}", flush=True)

# Second /api/status (cached)
t1 = time.time()
req3 = urllib.request.Request(base + "/api/status", headers={"Cookie": f"signal_session={session}"})
resp3 = urllib.request.urlopen(req3)
data2 = json.loads(resp3.read())
elapsed2 = time.time() - t1
print(f"Second /api/status (cached): {elapsed2:.3f}s", flush=True)

# Get stats request
t2 = time.time()
req4 = urllib.request.Request(base + "/api/stats", headers={"Cookie": f"signal_session={session}"})
try:
    resp4 = urllib.request.urlopen(req4)
    result = json.loads(resp4.read())
    elapsed3 = time.time() - t2
    print(f"Stats request: {elapsed3:.1f}s, result={result}", flush=True)
except urllib.error.HTTPError as e:
    elapsed3 = time.time() - t2
    print(f"Stats ERROR {e.code} in {elapsed3:.1f}s: {e.read().decode()}", flush=True)
