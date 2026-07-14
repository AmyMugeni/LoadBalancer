import asyncio
import http.client
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from collections import Counter

BASE_LB = "http://localhost:5000"
HOME_URL = f"{BASE_LB}/home"
REP_URL = f"{BASE_LB}/rep"
TOTAL_REQUESTS = 10_000
CONCURRENCY = 300
TIMEOUT_SECONDS = 8
SERVER_PATTERN = re.compile(r"Hello from Server:\s*(\d+)")
TARGETS = [2, 3, 4, 5, 6]
MAX_API_RETRIES = 40
API_RETRY_DELAY_SECONDS = 1


def curl_json(url, method="GET", payload=None):
    req = urllib.request.Request(url=url, method=method)
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    else:
        body = None

    last_error = None
    for _ in range(MAX_API_RETRIES):
        try:
            with urllib.request.urlopen(req, data=body, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, http.client.RemoteDisconnected, TimeoutError, ConnectionError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(API_RETRY_DELAY_SECONDS)

    raise RuntimeError(f"API call failed after retries: {method} {url}: {last_error}")


def get_replicas():
    data = curl_json(REP_URL)
    message = data.get("message", {})
    return int(message.get("N", 0)), list(message.get("replicas", []))


def set_replicas(target_n):
    current_n, _ = get_replicas()
    delta = target_n - current_n
    if delta > 0:
        curl_json(f"{BASE_LB}/add", method="POST", payload={"n": delta, "hostnames": []})
    elif delta < 0:
        curl_json(f"{BASE_LB}/rm", method="DELETE", payload={"n": -delta, "hostnames": []})
    return get_replicas()


def do_request(request_id: int):
    url = f"{HOME_URL}?request_id={request_id}"
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            status = resp.getcode()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        status = exc.code
    except Exception as exc:
        return {
            "ok": False,
            "server": None,
            "status": None,
            "latency_ms": (time.perf_counter() - start) * 1000,
            "error": str(exc),
        }

    match = SERVER_PATTERN.search(body)
    server = f"Server {match.group(1)}" if match else None
    ok = status == 200 and server is not None

    return {
        "ok": ok,
        "server": server,
        "status": status,
        "latency_ms": (time.perf_counter() - start) * 1000,
        "error": None if ok else "unexpected response",
    }


async def run_benchmark():
    queue = asyncio.Queue()
    for i in range(1, TOTAL_REQUESTS + 1):
        queue.put_nowait(i)

    results = []

    async def worker():
        while True:
            try:
                request_id = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            result = await asyncio.to_thread(do_request, request_id)
            results.append(result)
            queue.task_done()

    workers = [asyncio.create_task(worker()) for _ in range(CONCURRENCY)]
    await asyncio.gather(*workers)
    return results


def percentile_from_sorted(ordered_values, pct):
    if not ordered_values:
        return 0.0
    idx = int((pct / 100.0) * (len(ordered_values) - 1))
    return ordered_values[idx]


async def run_for_n(target_n):
    actual_n, replicas = set_replicas(target_n)

    started = time.perf_counter()
    results = await run_benchmark()
    elapsed = time.perf_counter() - started

    success = [r for r in results if r["ok"]]
    failed = [r for r in results if not r["ok"]]
    counts = Counter(r["server"] for r in success if r["server"])
    status_counts = Counter(str(r["status"]) for r in results)
    latencies = [r["latency_ms"] for r in success]
    ordered_latencies = sorted(latencies)

    avg_load_success_only = round((len(success) / actual_n) if actual_n > 0 else 0.0, 2)
    ideal_avg_load = round(TOTAL_REQUESTS / actual_n, 2) if actual_n > 0 else 0.0

    return {
        "target_n": target_n,
        "actual_n": actual_n,
        "replicas": replicas,
        "total_requests": TOTAL_REQUESTS,
        "successful_requests": len(success),
        "failed_requests": len(failed),
        "status_counts": dict(sorted(status_counts.items())),
        "duration_seconds": round(elapsed, 3),
        "throughput_rps": round((len(success) / elapsed) if elapsed > 0 else 0.0, 2),
        "latency_ms": {
            "mean": round((sum(latencies) / len(latencies)) if latencies else 0.0, 2),
            "p50": round(percentile_from_sorted(ordered_latencies, 50), 2),
            "p95": round(percentile_from_sorted(ordered_latencies, 95), 2),
            "p99": round(percentile_from_sorted(ordered_latencies, 99), 2),
        },
        "server_counts": dict(sorted(counts.items())),
        "average_load_per_server_success_only": avg_load_success_only,
        "ideal_average_load_per_server": ideal_avg_load,
    }


def reset_stack():
    subprocess.run(["make", "down"], check=True)
    subprocess.run(["make", "up"], check=True)


def wait_for_load_balancer_ready():
    for _ in range(MAX_API_RETRIES):
        try:
            n, _ = get_replicas()
            if n > 0:
                return
        except Exception:
            pass
        time.sleep(API_RETRY_DELAY_SECONDS)
    raise RuntimeError("Load balancer did not become ready in time")


def main():
    reset_stack()
    wait_for_load_balancer_ready()
    all_runs = []
    for n in TARGETS:
        print(f"Running benchmark for N={n} ...", flush=True)
        all_runs.append(asyncio.run(run_for_n(n)))

    report = {
        "config": {
            "targets": TARGETS,
            "total_requests": TOTAL_REQUESTS,
            "concurrency": CONCURRENCY,
        },
        "runs": all_runs,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
