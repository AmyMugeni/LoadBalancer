import json
import re
import subprocess
import time
import urllib.error
import urllib.request

BASE = "http://localhost:5000"
SERVER_MSG_RE = re.compile(r"Hello from Server:\s*(\d+)")


def request(method, path, payload=None, timeout=10):
    req = urllib.request.Request(BASE + path, method=method)
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, data=body, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            code = resp.getcode()
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        code = exc.code
    except Exception as exc:
        return None, None, str(exc)

    try:
        data = json.loads(text)
    except Exception:
        data = text
    return code, data, None


def wait_for_lb(max_wait=40):
    start = time.time()
    while time.time() - start < max_wait:
        code, data, _ = request("GET", "/rep", timeout=3)
        if code == 200 and isinstance(data, dict):
            return data
        time.sleep(1)
    raise RuntimeError("Load balancer did not become ready in time")


def find_request_id_for_server(server_id, max_probe=5000):
    for rid in range(1, max_probe + 1):
        code, data, _ = request("GET", f"/home?request_id={rid}")
        if code != 200 or not isinstance(data, dict):
            continue
        msg = data.get("message", "")
        match = SERVER_MSG_RE.search(msg)
        if match and int(match.group(1)) == server_id:
            return rid
    return None


def run():
    report = {
        "endpoint_tests": {},
        "failover_test": {},
    }

    rep = wait_for_lb()
    report["endpoint_tests"]["initial_rep"] = rep

    code, data, err = request("GET", "/rep")
    report["endpoint_tests"]["GET /rep"] = {"code": code, "ok": code == 200 and err is None}

    code, data, err = request("GET", "/home?request_id=123")
    ok_home = code == 200 and isinstance(data, dict) and "Hello from Server" in str(data.get("message", ""))
    report["endpoint_tests"]["GET /home"] = {"code": code, "ok": ok_home}

    code, data, err = request("GET", "/not-registered?request_id=123")
    report["endpoint_tests"]["GET /<unknown-path>"] = {"code": code, "ok": code == 404}

    code, data, err = request("POST", "/add", {"n": 1, "hostnames": []})
    ok_add = code == 200 and isinstance(data, dict) and data.get("status") == "successful"
    report["endpoint_tests"]["POST /add"] = {"code": code, "ok": ok_add}

    code, data, err = request("DELETE", "/rm", {"n": 1, "hostnames": []})
    ok_rm = code == 200 and isinstance(data, dict) and data.get("status") == "successful"
    report["endpoint_tests"]["DELETE /rm"] = {"code": code, "ok": ok_rm}

    code, data, err = request("DELETE", "/rm", {"n": 1, "hostnames": ["x", "y"]})
    report["endpoint_tests"]["DELETE /rm invalid payload"] = {"code": code, "ok": code == 400}

    # Failover scenario: kill server1 and verify LB replaces it quickly.
    target_hostname = "server1"
    target_server_id = 1
    target_request_id = find_request_id_for_server(target_server_id)

    report["failover_test"]["target_hostname"] = target_hostname
    report["failover_test"]["target_server_id"] = target_server_id
    report["failover_test"]["target_request_id"] = target_request_id

    if target_request_id is None:
        report["failover_test"]["ok"] = False
        report["failover_test"]["reason"] = "Could not find request_id mapped to server1"
        print(json.dumps(report, indent=2))
        return

    kill_started = time.time()
    kill_proc = subprocess.run(["docker", "rm", "-f", target_hostname], capture_output=True, text=True)
    report["failover_test"]["kill_exit_code"] = kill_proc.returncode

    max_wait_seconds = 20
    recovered = False
    recovery_seconds = None
    replacement_hostname = None
    probes = []

    while time.time() - kill_started < max_wait_seconds:
        code, data, err = request("GET", f"/home?request_id={target_request_id}", timeout=4)
        probes.append(code if code is not None else "EXC")

        rep_code, rep_data, _ = request("GET", "/rep", timeout=4)
        if rep_code == 200 and isinstance(rep_data, dict):
            replicas = rep_data.get("message", {}).get("replicas", [])
            for hostname in replicas:
                if hostname != target_hostname and hostname.startswith("s"):
                    replacement_hostname = hostname

        if code == 200 and replacement_hostname is not None:
            recovered = True
            recovery_seconds = round(time.time() - kill_started, 3)
            break

        time.sleep(0.25)

    report["failover_test"]["ok"] = recovered
    report["failover_test"]["recovery_seconds"] = recovery_seconds
    report["failover_test"]["replacement_hostname"] = replacement_hostname
    report["failover_test"]["probe_statuses_first_25"] = probes[:25]

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    run()
