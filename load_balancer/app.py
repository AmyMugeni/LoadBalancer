from flask import Flask, jsonify, request
from consistent_hash import ConsistentHash
import docker
import random
import string

docker_client = docker.from_env()
def random_hostname():
    return "S" + "".join(random.choices(string.digits, k=4))

app = Flask(__name__)
hash_ring = ConsistentHash()
servers = {}
for server_id in range(1, 4):

    hostname = f"Server{server_id}"

    servers[server_id] = hostname

    hash_ring.add_server(server_id)


@app.route("/rep", methods=["GET"])
def get_replicas():

    return jsonify({
        "message": {
            "N": len(servers),
            "replicas": list(servers.values())
        },
        "status": "successful"
    }), 200

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

    return jsonify({
        "message": {
            "N": len(servers) + n,
            "replicas": list(servers.values()) + hostnames
        },
        "status": "successful"
    }), 200
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)