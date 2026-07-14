#!/usr/bin/env python3
"""
薇美AI Pro — 3D雕塑视频 API 服务器
提供HTTP接口供前端调用
"""

import json
import os
import sys
import threading
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Store task status
running_tasks = {}


@app.route("/api/status", methods=["GET"])
def api_status():
    return jsonify({"ok": True, "service": "薇美AI Pro - 3D雕塑视频服务"})


@app.route("/api/upload", methods=["POST"])
def api_upload():
    """Upload a photo and start the pipeline."""
    if "photo" not in request.files:
        return jsonify({"ok": False, "error": "请上传照片"}), 400

    file = request.files["photo"]
    if not file.filename:
        return jsonify({"ok": False, "error": "文件名无效"}), 400

    # Save the uploaded file
    filename = f"input_{len(os.listdir(UPLOAD_DIR)) + 1}.jpg"
    filepath = os.path.join(UPLOAD_DIR, filename)
    file.save(filepath)

    # Create task
    task_id = f"task_{len(running_tasks) + 1}"
    running_tasks[task_id] = {
        "status": "pending",
        "progress": 0,
        "task_id": task_id,
        "message": "任务已创建",
        "input_path": filepath,
    }

    # Start pipeline in background
    thread = threading.Thread(target=run_pipeline_thread, args=(task_id, filepath), daemon=True)
    thread.start()

    return jsonify({"ok": True, "task_id": task_id, "status": "pending"})


@app.route("/api/task/<task_id>", methods=["GET"])
def api_task_status(task_id):
    """Query task status."""
    task = running_tasks.get(task_id)
    if not task:
        return jsonify({"ok": False, "error": "任务不存在"}), 404

    resp = {
        "ok": True,
        "task_id": task_id,
        "status": task["status"],
        "progress": task.get("progress", 0),
        "message": task.get("message", ""),
    }
    if task.get("sculpture_path"):
        resp["sculpture_url"] = f"/api/file/sculpture/{task_id}"
    if task.get("video_path"):
        resp["video_url"] = f"/api/file/video/{task_id}"
    if task.get("error"):
        resp["error"] = task["error"]

    return jsonify(resp)


@app.route("/api/file/sculpture/<task_id>", methods=["GET"])
def api_sculpture_file(task_id):
    """Download the sculpture image."""
    task = running_tasks.get(task_id)
    if not task or not task.get("sculpture_path"):
        return jsonify({"ok": False, "error": "文件不存在"}), 404
    return send_file(task["sculpture_path"], mimetype="image/png")


@app.route("/api/file/video/<task_id>", methods=["GET"])
def api_video_file(task_id):
    """Download the video."""
    task = running_tasks.get(task_id)
    if not task or not task.get("video_path"):
        return jsonify({"ok": False, "error": "文件不存在"}), 404
    return send_file(task["video_path"], mimetype="video/mp4")


def run_pipeline_thread(task_id, input_path):
    """Run the pipeline in background thread."""
    task = running_tasks[task_id]
    task["status"] = "running"
    task["progress"] = 10
    task["message"] = "正在生成3D大理石雕塑..."

    try:
        # Import and run pipeline
        sys.path.insert(0, os.path.dirname(__file__))
        from sculpture_pipeline import step1_generate_sculpture, step2_generate_video

        api_key = os.getenv("DOUBAO_API_KEY")
        if not api_key:
            task["status"] = "failed"
            task["error"] = "请设置 DOUBAO_API_KEY 环境变量"
            return

        task_dir = os.path.join(OUTPUT_DIR, task_id)
        os.makedirs(task_dir, exist_ok=True)

        # STEP 1
        task["message"] = "STEP 1/3: AI分析照片并生成3D大理石雕塑..."
        task["progress"] = 20

        sculpture_path = step1_generate_sculpture(
            api_key, input_path, task_dir,
        )

        if not sculpture_path or not os.path.exists(sculpture_path):
            task["status"] = "failed"
            task["error"] = "雕塑生成失败，请检查照片清晰度后重试"
            return

        task["sculpture_path"] = sculpture_path
        task["progress"] = 50
        task["message"] = "STEP 2/3: 3D大理石雕塑已完成！正在生成旋转展示视频..."

        # STEP 2
        video_path = step2_generate_video(
            api_key, sculpture_path, task_dir,
        )

        if not video_path or not os.path.exists(video_path):
            task["status"] = "failed"
            task["error"] = "视频生成失败，但雕塑图已生成完毕"
            task["progress"] = 60
            return

        task["video_path"] = video_path
        task["status"] = "completed"
        task["progress"] = 100
        task["message"] = "✅ 全部完成！3D雕塑旋转视频已生成"

    except Exception as e:
        task["status"] = "failed"
        task["error"] = str(e)
        task["message"] = f"管线异常: {str(e)}"


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    print(f"薇美AI Pro 3D雕塑视频服务启动: http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
