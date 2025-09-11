from flask import Flask, jsonify
import os

app = Flask(__name__)

@app.get("/")
def root():
    return "OK", 200

@app.get("/healthz")
def healthz():
    return jsonify(status="healthy"), 200


def start_health_server(port: int | None = None):
    """Start a minimal HTTP server for Azure health checks.

    Azure App Service on Linux pings the container on a specific port (default 8000).
    This server ensures the container responds so the app is considered healthy.
    """
    port = int(port or os.getenv("PORT") or os.getenv("WEBSITES_PORT") or 8000)
    # Run in production-friendly mode without reloader and with 0.0.0.0 binding
    app.run(host="0.0.0.0", port=port, use_reloader=False)
