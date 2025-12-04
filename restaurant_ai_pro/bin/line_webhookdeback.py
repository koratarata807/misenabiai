#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flask import Flask, request

app = Flask(__name__)

# ① デバッグ用：どんなURLでも全部ここで受ける
@app.route("/", defaults={"path": ""}, methods=["GET", "POST"])
@app.route("/<path:path>", methods=["GET", "POST"])
def catch_all(path):
    print("=== got request from LINE ===")
    print("PATH:", path)
    print("METHOD:", request.method)
    print("HEADERS:", dict(request.headers))
    try:
        print("JSON:", request.get_json())
    except Exception:
        print("JSON: (parse error)")

    # とりあえず 200 を返す
    return "OK", 200


if __name__ == "__main__":
    # 8000番で待ち受け（今まで通り）
    app.run(host="0.0.0.0", port=8000, debug=True)
