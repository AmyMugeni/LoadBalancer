import asyncio
import json
import re
import time
import urllib.error
import urllib.request
from collections import Counter

BASE_URL = "http://localhost:5000/home"
TOTAL_REQUESTS = 10_000
CONCURRENCY = 300
TIMEOUT_SECONDS = 8
SERVER_PATTERN = re.compile(r"Hello from Server:\s*(\d+)")


def do_request(request_id: int):
    url = f"{BASE_URL}?request_id={request_id}"
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
    semaphore = asyncio.Semaphore(CONCURRENCY)
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

            async with semaphore:
                result = await asyncio.to_thread(do_request, request_id)
                results.append(result)
            queue.task_done()

    workers = [asyncio.create_task(worker()) for _ in range(CONCURRENCY)]
    await asyncio.gather(*workers)

    return results


def percentile(values, pct):
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = int((pct / 100.0) * (len(ordered) - 1))
    return ordered[idx]


async def main():
    started = time.perf_counter()
    results = await run_benchmark()
    elapsed = time.perf_counter() - started

    success = [r for r in results if r["ok"]]
    failed = [r for r in results if not r["ok"]]

    counts = Counter(r["server"] for r in success if r["server"] is not None)
    status_counts = Counter(str(r["status"]) for r in results)
    latencies = [r["latency_ms"] for r in success]

    summary = {
        "total_requests": TOTAL_REQUESTS,
        "concurrency": CONCURRENCY,
        "successful_requests": len(success),
        "failed_requests": len(failed),
        "duration_seconds": round(elapsed, 3),
        "throughput_rps": round((len(success) / elapsed) if elapsed > 0 else 0.0, 2),
        "latency_ms": {
            "mean": round((sum(latencies) / len(latencies)) if latencies else 0.0, 2),
            "p50": round(percentile(latencies, 50), 2),
            "p95": round(percentile(latencies, 95), 2),
            "p99": round(percentile(latencies, 99), 2),
        },
        "status_counts": dict(sorted(status_counts.items())),
        "server_counts": dict(sorted(counts.items())),
        "error_examples": [r["error"] for r in failed[:5]],
    }

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
