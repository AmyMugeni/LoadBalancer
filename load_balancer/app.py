from flask import Flask, jsonify, request
from consistent_hash import ConsistentHash
import importlib
import os
import random
import string
from urllib import error as url_error
from urllib import request as url_request


def random_hostname():
    return "s" + "".join(random.choices(string.digits, k=4))


def _load_docker_client():
    try:
        docker_module = importlib.import_module("docker")
        return docker_module.from_env()
    except Exception:
        return None


docker_client = _load_docker_client()
SERVER_IMAGE = os.getenv("SERVER_IMAGE", "server:latest")
SERVER_PORT = int(os.getenv("SERVER_PORT", "5000"))
DOCKER_NETWORK = os.getenv("DOCKER_NETWORK", "distributedloadbalancer_default")


def create_server(server_id, hostname, create_container=True):
    if create_container and docker_client is not None:
        try:
            docker_client.containers.run(
                image=SERVER_IMAGE,
                name=hostname,
                detach=True,
                environment={"SERVER_ID": str(server_id)},
                network=DOCKER_NETWORK,
            )
        except Exception as exc:
            raise RuntimeError(f"Failed to create container '{hostname}': {exc}") from exc

    servers[server_id] = hostname
    hash_ring.add_server(server_id)
    print(f"Registered Server {server_id} ({hostname})")


def get_server_id_by_hostname(hostname):
    for server_id, current_hostname in servers.items():
        if current_hostname == hostname:
            return server_id
    return None


def remove_server(server_id, remove_container=True):
    hostname = servers.get(server_id)
    if hostname is None:
        return None

    hash_ring.remove_server(server_id)
    del servers[server_id]

    if remove_container and docker_client is not None:
        try:
            container = docker_client.containers.get(hostname)
            container.remove(force=True)
        except Exception:
            # Best effort cleanup: server is already removed from LB state.
            pass

    print(f"Removed Server {server_id} ({hostname})")
    return hostname


def next_server_id():
    if not servers:
        return 1
    return max(servers) + 1


def select_backend_server(request_id_raw):
    try:
        request_id = int(request_id_raw) if request_id_raw is not None else random.randint(1, 1_000_000)
    except ValueError:
        return None, "request_id must be an integer"

    server_id = hash_ring.get_server(request_id)
    hostname = servers.get(server_id)
    if hostname is None:
        return None, "Server mapping is inconsistent"
    return hostname, None


def proxy_to_server(hostname, path):
    clean_path = path.lstrip("/")
    query = request.query_string.decode("utf-8")
    target_url = f"http://{hostname}:{SERVER_PORT}/{clean_path}"
    if query:
        target_url = f"{target_url}?{query}"
    try:
        with url_request.urlopen(target_url, timeout=3) as response:
            body = response.read().decode("utf-8")
            return body, response.getcode(), response.headers.get_content_type()
    except url_error.HTTPError as exc:
        return exc.read().decode("utf-8"), exc.code, "application/json"
    except Exception as exc:
        return jsonify({
            "message": f"Could not reach backend '{hostname}' at {target_url}: {exc}",
            "status": "failure",
        }), 502

app = Flask(__name__)
hash_ring = ConsistentHash()
servers = {}
INITIAL_REPLICAS = int(os.getenv("INITIAL_REPLICAS", "3"))
AUTO_CREATE_CONTAINERS = os.getenv("AUTO_CREATE_CONTAINERS", "true").lower() == "true"

for server_id in range(1, INITIAL_REPLICAS + 1):
    create_server(server_id, f"server{server_id}", create_container=AUTO_CREATE_CONTAINERS)


@app.route("/rep", methods=["GET"])
def get_replicas():

    return jsonify({
        "message": {
            "N": len(servers),
            "replicas": list(servers.values())
        },
        "status": "successful"
    }), 200


@app.route("/home", methods=["GET"])
def route_request():
    if not servers:
        return jsonify({"message": "No backend servers available", "status": "failure"}), 503

    hostname, err = select_backend_server(request.args.get("request_id"))
    if err is not None:
        return jsonify({"message": err, "status": "failure"}), 400 if "request_id" in err else 500

    proxied = proxy_to_server(hostname, "home")
    if isinstance(proxied, tuple) and len(proxied) == 3:
        body, status_code, content_type = proxied
        return app.response_class(body, status=status_code, mimetype=content_type)
    return proxied


@app.route("/<path:subpath>", methods=["GET"])
def route_any_path(subpath):
    if not servers:
        return jsonify({"message": "No backend servers available", "status": "failure"}), 503

    hostname, err = select_backend_server(request.args.get("request_id"))
    if err is not None:
        return jsonify({"message": err, "status": "failure"}), 400 if "request_id" in err else 500

    proxied = proxy_to_server(hostname, subpath)
    if isinstance(proxied, tuple) and len(proxied) == 3:
        body, status_code, content_type = proxied
        return app.response_class(body, status=status_code, mimetype=content_type)
    return proxied

@app.route("/add", methods=["POST"])
def add_servers():

    data = request.get_json()

    n = data.get("n", 0)
    hostnames = data.get("hostnames", [])
    if len(hostnames) > n:
        return jsonify({
        "message":
            "<Error> Length of hostname list is more than newly added instances",
        "status": "failure"
    }), 400
    while len(hostnames) < n:
        hostnames.append(random_hostname())

    created = []
    for hostname in hostnames:
        server_id = next_server_id()
        create_server(server_id, hostname, create_container=AUTO_CREATE_CONTAINERS)
        created.append(hostname)

    return jsonify({
        "message": {
            "N": len(servers),
            "replicas": list(servers.values()),
            "created": created,
        },
        "status": "successful"
    }), 200


@app.route("/rm", methods=["DELETE"])
def remove_servers():
    data = request.get_json(silent=True) or {}

    n = data.get("n")
    hostnames = data.get("hostnames", [])

    if not isinstance(n, int) or n <= 0:
        return jsonify({
            "message": "<Error> 'n' must be a positive integer",
            "status": "failure",
        }), 400

    if not isinstance(hostnames, list):
        return jsonify({
            "message": "<Error> 'hostnames' must be a list",
            "status": "failure",
        }), 400

    if len(hostnames) > n:
        return jsonify({
            "message": "<Error> Length of hostname list is more than instances requested for removal",
            "status": "failure",
        }), 400

    if n > len(servers):
        return jsonify({
            "message": "<Error> Requested removals exceed number of removable instances",
            "status": "failure",
        }), 400

    if len(hostnames) != len(set(hostnames)):
        return jsonify({
            "message": "<Error> Duplicate hostnames in payload",
            "status": "failure",
        }), 400

    unknown_hostnames = [hostname for hostname in hostnames if hostname not in set(servers.values())]
    if unknown_hostnames:
        return jsonify({
            "message": f"<Error> Unknown hostnames requested for removal: {unknown_hostnames}",
            "status": "failure",
        }), 400

    selected_hostnames = list(hostnames)
    remaining = n - len(selected_hostnames)
    if remaining > 0:
        candidates = [hostname for hostname in servers.values() if hostname not in selected_hostnames]
        selected_hostnames.extend(random.sample(candidates, remaining))

    removed = []
    for hostname in selected_hostnames:
        server_id = get_server_id_by_hostname(hostname)
        if server_id is None:
            continue
        removed_hostname = remove_server(server_id, remove_container=True)
        if removed_hostname is not None:
            removed.append(removed_hostname)

    return jsonify({
        "message": {
            "N": len(servers),
            "replicas": list(servers.values()),
            "removed": removed,
        },
        "status": "successful",
    }), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)