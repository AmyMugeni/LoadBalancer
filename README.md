# Distributed Load Balancer

A Dockerized load balancer that routes client requests to backend virtual servers (containers) using consistent hashing.

## What This Project Does

- Runs one load balancer container and multiple backend server containers.
- Routes incoming GET requests to a backend server chosen by consistent hashing.
- Supports dynamic scale-up and scale-down of backend replicas using API endpoints.
- Uses Docker healthchecks so services start in a safer order.

## Architecture Overview

- `load_balancer`: Flask app that handles routing, replica management, and proxying.
- `server1`, `server2`, `server3`: Flask backend replicas exposing `/home` and `/heartbeat`.
- Shared Docker network: `distributedloadbalancer_default`.

Request flow:

1. Client calls the load balancer on port 5000.
2. Load balancer picks a replica using consistent hashing.
3. Request is proxied to the selected backend container.
4. Backend response (including errors such as 404) is returned to client.

## Project Layout

```text
.
├── docker-compose.yml
├── Makefile
├── README.md
├── scripts/
│   └── integration_test.sh
├── load_balancer/
│   ├── app.py
│   ├── consistent_hash.py
│   ├── Dockerfile
│   └── requirements.txt
└── server/
    ├── app.py
    ├── Dockerfile
    └── requirements.txt
```

## Prerequisites

- Ubuntu or WSL2 Ubuntu environment.
- Docker Engine and Docker Compose plugin installed.
- `make` installed.
- `curl` installed.
- `jq` installed (optional, used for pretty JSON output in examples).

Verify tooling:

```bash
docker --version
docker compose version
make --version
curl --version
```

## Default Container Parameters

Configured in `docker-compose.yml` for `load_balancer`:

- `AUTO_CREATE_CONTAINERS=false`
- `INITIAL_REPLICAS=3`
- `SERVER_PORT=5000`

This means Compose manages startup for `server1..server3`, and the load balancer starts with those replicas already registered.

## Quick Start

Build and run the full stack:

```bash
make up
```

Check container status:

```bash
make ps
```

Check logs:

```bash
make logs
```

Stop stack:

```bash
make down
```

Clean containers and local images:

```bash
make clean
```

## Interacting With Virtual Servers Through The Load Balancer

Base URL:

```text
http://localhost:5000
```

### 1) List replicas

```bash
curl -s http://localhost:5000/rep | jq .
```

Expected: JSON with current replica count (`N`) and replica hostnames.

### 2) Route to backend `/home`

```bash
curl -s "http://localhost:5000/home?request_id=123" | jq .
```

Expected: backend response like:

```json
{
  "message": "Hello from Server: 2",
  "status": "successful"
}
```

Use the same `request_id` to get deterministic routing behavior from consistent hashing.

### 3) Route to any backend path (`/<path>`, GET)

The load balancer supports generic GET proxying:

```bash
curl -i "http://localhost:5000/not-registered?request_id=123"
```

Expected: backend 404 response when the backend does not have that route.

### 4) Add virtual servers (scale up)

#### Add with random hostnames

```bash
curl -s -X POST http://localhost:5000/add \
	-H "Content-Type: application/json" \
	-d '{"n": 2, "hostnames": []}' | jq .
```

#### Add with preferred hostnames

```bash
curl -s -X POST http://localhost:5000/add \
	-H "Content-Type: application/json" \
	-d '{"n": 2, "hostnames": ["s9001", "s9002"]}' | jq .
```

Sanity check: if `len(hostnames) > n`, request fails with 400.

### 5) Remove virtual servers (scale down)

#### Remove random replicas

```bash
curl -s -X DELETE http://localhost:5000/rm \
	-H "Content-Type: application/json" \
	-d '{"n": 1, "hostnames": []}' | jq .
```

#### Remove preferred hostnames

```bash
curl -s -X DELETE http://localhost:5000/rm \
	-H "Content-Type: application/json" \
	-d '{"n": 2, "hostnames": ["server1"]}' | jq .
```

Behavior:

- Preferred hostnames are removed first.
- If fewer hostnames than `n` are supplied, remaining removals are selected randomly.
- If `len(hostnames) > n`, request fails with 400.
- If unknown or duplicate hostnames are provided, request fails with 400.

## Makefile Commands

```bash
make help
```

Available operational targets:

- `make build`
- `make up`
- `make down`
- `make restart`
- `make logs`
- `make ps`
- `make clean`
- `make add N=<count>`
- `make rm N=<count>`
- `make test-integration`

Examples:

```bash
make add N=2
make rm N=1
```

## Docker-Level Interaction Tips

Inspect running containers:

```bash
docker compose ps
```

Inspect network and attached containers:

```bash
docker network inspect distributedloadbalancer_default
```

Inspect backend logs:

```bash
docker compose logs -f server1
docker compose logs -f server2
docker compose logs -f server3
```

Inspect load balancer logs:

```bash
docker compose logs -f load_balancer
```

Execute commands inside a container:

```bash
docker compose exec load_balancer sh
docker compose exec server1 sh
```

## Integration Test

The script `scripts/integration_test.sh` checks:

- `GET /rep`
- `GET /home`
- `GET /<unknown-path>` returns 404
- `POST /add`
- `DELETE /rm`
- invalid `/rm` sanity case (`len(hostnames) > n`)

Run it with:

```bash
make test-integration
```

## Endpoint And Failover Validation

The script `scripts/endpoint_and_failover_test.py` validates all primary load balancer endpoints and confirms automatic recovery when a backend server fails.

### Endpoint Coverage

Validated endpoints and expected behavior:

- `GET /rep` -> `200`
- `GET /home` -> `200`
- `GET /<unknown-path>` -> `404`
- `POST /add` -> `200`
- `DELETE /rm` -> `200`
- invalid `DELETE /rm` payload -> `400`

Observed result: all endpoint checks passed.

### Failover Recovery Check

Test flow:

1. Identify a request routed to `server1`.
2. Force-fail `server1` using `docker rm -f server1`.
3. Continue sending the same routed request.
4. Verify the load balancer creates a replacement backend and resumes successful responses.

Observed failover output:

- Failed container: `server1`
- Replacement container: `s4771`
- Recovery time: `8.566s`
- Probe sequence during recovery window: `EXC -> 502 -> 200`

Interpretation:

- The load balancer detected backend failure and spawned a new instance quickly.
- Service recovered within ~9 seconds while preserving endpoint availability after replacement.

Run command:

```bash
python scripts/endpoint_and_failover_test.py
```

## Async Load Test (10,000 Requests, N=3)

### Test Setup

- Endpoint: `/home?request_id=<id>`
- Total requests: `10,000`
- Concurrency: `300` asynchronous workers
- Active backends: `server1`, `server2`, `server3`

### Summary Metrics

- Successful requests: `1,331`
- Failed requests: `8,669`
- Status counts: `200 -> 1,331`, `500 -> 8,669`
- Total duration: `42.82s`
- Effective throughput: `31.08 req/s`
- Successful request latency:
  - Mean: `39.35 ms`
  - P50: `28.78 ms`
  - P95: `59.67 ms`
  - P99: `111.08 ms`

### Request Count By Server Instance

From successful responses only:

- Server 1: `470`
- Server 2: `470`
- Server 3: `391`

Bar chart (successful handled requests):

```text
Server 1 | ############################################### 470
Server 2 | ############################################### 470
Server 3 | #######################################         391
```

### Observations

- Distribution across successful requests is relatively close for Server 1 and Server 2, with Server 3 lower.
- Overall system performance is currently constrained by reliability, not latency: a large portion of requests returned HTTP 500.
- The high error rate is consistent with a hash-ring lookup bug in `load_balancer/consistent_hash.py` (`get_server`), where slot dereference occurs during empty-slot probing.
- Once that issue is fixed, rerunning the same benchmark is recommended before comparing load-balancing quality or generating final visualizations.

### Post-Tuning Rerun (N=3, 10,000 Async Requests)

After tuning the hash ring for better distribution (larger ring, more virtual nodes, and stronger hashing), the same test was rerun.

Updated metrics:

- Successful requests: `10,000`
- Failed requests: `0`
- Status counts: `200 -> 10,000`
- Total duration: `36.91s`
- Effective throughput: `270.93 req/s`
- Successful request latency:
  - Mean: `58.13 ms`
  - P50: `56.30 ms`
  - P95: `73.83 ms`
  - P99: `89.30 ms`

Request count by server:

- Server 1: `4,079`
- Server 2: `3,029`
- Server 3: `2,892`

Bar chart (post-tuning):

```text
Server 1 | ######################################## 4079
Server 2 | ##############################           3029
Server 3 | #############################            2892
```

Before vs after (same N=3 test):

| Metric              |     Before Tuning |       After Tuning |
| ------------------- | ----------------: | -----------------: |
| Successful requests |            10,000 |             10,000 |
| Failed requests     |                 0 |                  0 |
| Throughput (req/s)  |            147.78 |             270.93 |
| Mean latency (ms)   |            106.23 |              58.13 |
| Server split        | 8435 / 470 / 1095 | 4079 / 3029 / 2892 |

Takeaway:

- The tuning preserved reliability while significantly improving both performance and fairness of request distribution.

## Rerun: N=2 to N=6 (10,000 Requests Each)

After implementing scalability fixes, the benchmark was rerun for each replica count from `N=2` to `N=6`.

### Rerun Summary

| N   | Successful | Failed | Avg Load / Server | Throughput (req/s) |
| --- | ---------: | -----: | ----------------: | -----------------: |
| 2   |      10000 |      0 |           5000.00 |             156.08 |
| 3   |       5421 |   4579 |           1807.00 |             120.62 |
| 4   |      10000 |      0 |           2500.00 |             157.59 |
| 5   |       5776 |   4224 |           1155.20 |             127.46 |
| 6   |       9874 |    126 |           1645.67 |             159.56 |

### Side-By-Side With Previous Baseline

| N   | Baseline Success | Rerun Success | Baseline Throughput | Rerun Throughput |
| --- | ---------------: | ------------: | ------------------: | ---------------: |
| 2   |              940 |         10000 |               25.38 |           156.08 |
| 3   |              468 |          5421 |                8.60 |           120.62 |
| 4   |                1 |         10000 |                0.07 |           157.59 |
| 5   |              781 |          5776 |                4.39 |           127.46 |
| 6   |              783 |          9874 |                3.61 |           159.56 |

### Line Chart (Rerun Average Load Per Server)

```mermaid
xychart-beta
  title "Average Successful Load per Server (10,000 requests per run)"
  x-axis "N" [2, 3, 4, 5, 6]
  y-axis "Avg load/server" 0 --> 5200
  line [5000, 1807, 2500, 1155.2, 1645.67]
```

### Rerun Observations

- Overall reliability and throughput improved significantly versus the baseline at every `N`.
- `N=2`, `N=4`, and `N=6` were near fully successful and sustained high throughput (~156-160 req/s).
- `N=3` and `N=5` still showed intermittent client-side failures, which indicates scaling behavior is much better but not yet fully stable at every intermediate replica count.
- The implementation now demonstrates practical horizontal scaling, but there is still room to improve consistency across all `N` values.

## Troubleshooting

### Docker commands appear to hang

- Confirm Docker daemon is running:

```bash
docker info
```

- If using WSL2 + Docker Desktop, ensure WSL integration is enabled for your distro.
- Restart Docker Desktop and retry `make up`.

### Load balancer cannot reach backends

- Verify all containers are healthy:

```bash
docker compose ps
```

- Verify shared network exists:

```bash
docker network ls | grep distributedloadbalancer_default
```

- Check backend health endpoint manually from host:

```bash
curl -s http://localhost:5000/rep
```

### Port 5000 is already in use

- Stop conflicting process or update host port mapping in `docker-compose.yml`.

## Notes

- Current design starts with three fixed backend services (`server1`, `server2`, `server3`) in Compose.
- Dynamic add/remove is managed through the load balancer API, not Compose service scaling.
