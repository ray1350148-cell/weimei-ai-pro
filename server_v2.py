#!/usr/bin/env python3
"""
薇美AI Pro — 通用后端API服务
用户自备API Key，支持多平台接入
"""
import os, json, base64, time, threading, uuid, urllib.request, urllib.error
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

WORK_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(WORK_DIR, "server_uploads")
OUTPUT_DIR = os.path.join(WORK_DIR, "server_outputs")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

running_tasks = {}


# ============================================================
# 各平台API端点映射
# ============================================================
PROVIDERS = {
    "siliconflow": {
        "name": "硅基流动",
        "chat": "https://api.siliconflow.cn/v1/chat/completions",
        "image": "https://api.siliconflow.cn/v1/images/generations",
        "models": {
            "image": ["black-forest-labs/FLUX.1-dev", "stabilityai/stable-diffusion-3-5-large"],
            "video": []
        }
    },
    "toapis": {
        "name": "ToAPIs",
        "image": "https://toapis.com/v1/images/generations",
        "video": "https://toapis.com/v1/videos/generations",
        "models": {
            "image": ["gemini-3-pro-image-preview", "gpt-image-2", "seedream"],
            "video": ["seedance-2", "kling-v3", "veo3.1-quality-official"]
        }
    },
    "ark": {
        "name": "火山引擎 Ark",
        "image": "https://ark.cn-beijing.volces.com/api/v3/images/generations",
        "video": "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks",
        "video_query": "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks/{task_id}",
        "models": {
            "image": ["doubao-seedream-4-5", "doubao-seedream-3-0-t2i"],
            "video": ["doubao-seedance-1-0-lite-t2v", "doubao-seedance-1-0-lite-i2v"]
        }
    },
    "openai": {
        "name": "OpenAI 兼容",
        "base": "",  # 用户自定义
        "image": "{base}/images/generations",
        "video": "{base}/video/generations",
        "models": {
            "image": ["dall-e-3", "自定义"],
            "video": ["自定义"]
        }
    }
}


# ============================================================
# 图片生成
# ============================================================
@app.route("/api/generate/image", methods=["POST"])
def api_generate_image():
    data = request.get_json(force=True) or {}
    provider = data.get("provider", "siliconflow")
    api_key = data.get("api_key", "")
    prompt = data.get("prompt", "")
    image_b64 = data.get("image", "")
    model = data.get("model", "")
    size = data.get("size", "1024x1024")

    if not api_key:
        return jsonify({"ok": False, "error": "请先在设置中配置 API Key"}), 400
    if not prompt:
        return jsonify({"ok": False, "error": "缺少 prompt"}), 400

    provider_cfg = PROVIDERS.get(provider)
    if not provider_cfg:
        return jsonify({"ok": False, "error": f"不支持的平台: {provider}"}), 400

    try:
        endpoint = provider_cfg.get("image", "")
        if provider == "openai":
            base = provider_cfg.get("base", "")
            if not base: return jsonify({"ok":False,"error":"OpenAI 兼容模式需要填写 Base URL"}),400
            endpoint = f"{base.rstrip('/')}/images/generations"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "WeiMeiAI-Pro/1.0"
        }

        body = {"model": model or _default_model(provider, "image"), "prompt": prompt, "size": size, "n": 1}
        if image_b64:
            body["image_url"] = f"data:image/jpeg;base64,{image_b64}"

        req = urllib.request.Request(endpoint, data=json.dumps(body).encode(), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode())

        # 统一返回格式
        img_url = _extract_image_url(result)
        if img_url:
            return jsonify({"ok": True, "url": img_url})
        return jsonify({"ok": False, "error": f"生成失败: {str(result)[:200]}"}), 500

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 500


# ============================================================
# 视频生成
# ============================================================
@app.route("/api/generate/video", methods=["POST"])
def api_generate_video():
    data = request.get_json(force=True) or {}
    provider = data.get("provider", "toapis")
    api_key = data.get("api_key", "")
    prompt = data.get("prompt", "")
    image_b64 = data.get("image", "")
    model = data.get("model", "")
    duration = data.get("duration", 5)

    if not api_key:
        return jsonify({"ok": False, "error": "请先在设置中配置 API Key"}), 400
    if not prompt:
        return jsonify({"ok": False, "error": "缺少 prompt"}), 400

    task_id = f"vtask_{uuid.uuid4().hex[:12]}"
    running_tasks[task_id] = {"status": "queued", "progress": 0, "message": "排队中"}
    thread = threading.Thread(target=_run_video_gen, args=(task_id, provider, api_key, prompt, image_b64, model, duration), daemon=True)
    thread.start()
    return jsonify({"ok": True, "task_id": task_id})


@app.route("/api/task/<task_id>", methods=["GET"])
def api_task_status(task_id):
    task = running_tasks.get(task_id)
    if not task:
        return jsonify({"ok": False, "error": "任务不存在"}), 404
    resp = {"ok": True, "status": task["status"], "progress": task.get("progress", 0), "message": task.get("message", "")}
    if task.get("result_url"): resp["result_url"] = task["result_url"]
    if task.get("error"): resp["error"] = task["error"]
    return jsonify(resp)


@app.route("/api/file/<filename>", methods=["GET"])
def api_serve_file(filename):
    path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(path):
        return jsonify({"ok": False, "error": "文件不存在"}), 404
    mime = "video/mp4" if filename.endswith(".mp4") else "image/png"
    return send_file(path, mimetype=mime)


@app.route("/api/providers", methods=["GET"])
def api_list_providers():
    """返回支持的平台列表"""
    result = {}
    for k, v in PROVIDERS.items():
        result[k] = {"name": v["name"], "models": v.get("models", {})}
    return jsonify({"ok": True, "providers": result})


# ============================================================
# 工具函数
# ============================================================
def _default_model(provider, type_):
    models = PROVIDERS.get(provider, {}).get("models", {}).get(type_, [])
    return models[0] if models else ""


def _extract_image_url(result):
    """从不同API返回中提取图片URL"""
    if isinstance(result, dict):
        data = result.get("data", [])
        if data and isinstance(data, list):
            item = data[0]
            for field in ["url", "b64_json"]:
                if item.get(field):
                    return item[field]
        for field in ["url", "image_url", "result_url"]:
            if result.get(field):
                return result[field]
    return ""


def _run_video_gen(task_id, provider, api_key, prompt, image_b64, model, duration):
    task = running_tasks[task_id]
    task["status"] = "running"
    task["progress"] = 10
    task["message"] = "提交视频任务..."

    provider_cfg = PROVIDERS.get(provider)
    if not provider_cfg:
        task["status"] = "failed"; task["error"] = "不支持的平台"; return

    endpoint = provider_cfg.get("video", "")
    if not endpoint:
        task["status"] = "failed"; task["error"] = "该平台不支持视频生成"; return

    if provider == "openai":
        base = provider_cfg.get("base", "")
        if not base: task["status"]="failed"; task["error"]="缺少 Base URL"; return
        endpoint = f"{base.rstrip('/')}/video/generations"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "WeiMeiAI-Pro/1.0"
    }

    try:
        body = {"model": model or _default_model(provider, "video")}
        content = [{"type": "text", "text": f"{prompt} --dur {duration} --fps 24 --rs 720p"}]
        if image_b64:
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}})
        body["content"] = content

        req = urllib.request.Request(endpoint, data=json.dumps(body).encode(), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode())

        remote_id = result.get("id") or result.get("task_id", "")
        if not remote_id:
            task["status"] = "failed"; task["error"] = f"提交失败: {str(result)[:200]}"; return

        task["message"] = "视频生成中..."
        deadline = time.time() + 300
        query_endpoint = provider_cfg.get("video_query", f"{endpoint}/{remote_id}")

        while time.time() < deadline:
            time.sleep(5)
            qreq = urllib.request.Request(query_endpoint, headers=headers)
            with urllib.request.urlopen(qreq, timeout=30) as qresp:
                status_resp = json.loads(qresp.read().decode())
            status = status_resp.get("status", "")
            task["progress"] = status_resp.get("progress", task.get("progress", 0))

            if status in ("succeeded", "completed", "finished"):
                video_url = _extract_video_url(status_resp)
                if video_url:
                    filename = f"video_{task_id}.mp4"
                    local_path = os.path.join(OUTPUT_DIR, filename)
                    dl_req = urllib.request.Request(video_url, headers={"User-Agent": "WeiMeiAI-Pro/1.0"})
                    with urllib.request.urlopen(dl_req, timeout=120) as f:
                        with open(local_path, "wb") as out: out.write(f.read())
                    task["result_url"] = f"/api/file/{filename}"
                    task["status"] = "completed"; task["progress"] = 100; task["message"] = "视频已生成"
                    return
                task["status"] = "failed"; task["error"] = "未获取到视频URL"; return
            elif status in ("failed", "error", "canceled"):
                task["status"] = "failed"; task["error"] = f"生成失败"; return

        task["status"] = "failed"; task["error"] = "超时"
    except Exception as e:
        task["status"] = "failed"; task["error"] = str(e)[:300]


def _extract_video_url(result):
    """从视频API返回中提取视频URL"""
    if isinstance(result, dict):
        content = result.get("content", {})
        if content.get("video_url"): return content["video_url"]
        res = result.get("result", {})
        if isinstance(res, dict):
            data = res.get("data", [])
            if data and data[0].get("url"): return data[0]["url"]
        if isinstance(res, list) and res and res[0].get("url"): return res[0]["url"]
        if result.get("url"): return result["url"]
    return ""


# ============================================================
# 启动
# ============================================================
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    print(f"\n{'='*50}")
    print(f"  薇美AI Pro 后端服务")
    print(f"{'='*50}")
    print(f"  地址: http://0.0.0.0:{port}")
    print(f"  接口:")
    print(f"    GET  /api/providers       - 查看支持的平台")
    print(f"    POST /api/generate/image  - 图片生成")
    print(f"    POST /api/generate/video  - 视频生成(异步)")
    print(f"    GET  /api/task/<id>       - 任务状态查询")
    print(f"    GET  /api/file/<name>     - 文件下载")
    print(f"{'='*50}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
