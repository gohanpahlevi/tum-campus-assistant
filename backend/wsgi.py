import os

from flask import send_file, send_from_directory

from api_v2 import api_v2_instance

app = api_v2_instance.app

STATIC = "static"


@app.route("/")
def serve_index():
    return send_file(os.path.join(STATIC, "index.html"))


@app.route("/<path:path>")
def serve_asset(path):
    if path.startswith("api/"):
        return {"error": "Not found", "status_code": 404}, 404
    if os.path.exists(os.path.join(STATIC, path)):
        return send_from_directory(STATIC, path)
    return send_file(os.path.join(STATIC, "index.html"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
