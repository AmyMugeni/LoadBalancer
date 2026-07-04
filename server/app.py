from flask import Flask, jsonify, request
import os
app = Flask(__name__)
@app.route("/home", methods=["GET"])
def home():
    return jsonify({
    "message": f"Hello from Server: {SERVER_ID}",
    "status": "successful"
})
@app.route("/heartbeat", methods=["GET"])
def heartbeat():
    return "I'm alive", 200



SERVER_ID = os.getenv("SERVER_ID")
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)