#!/usr/bin/env python3
"""
薇美AI Pro — 3D人像雕塑视频生成管线
将真人照片转化为3D大理石雕塑，并生成旋转展示视频

使用方式：
  python sculpture_pipeline.py --input /path/to/photo.jpg --output ./output

环境变量：
  DOUBAO_API_KEY          必填 - 火山引擎Ark API Key
  DOUBAO_IMAGE_MODEL      选填 - 图像模型 (默认: doubao-seedream-4-5)
  DOUBAO_VIDEO_MODEL      选填 - 视频模型 (默认: doubao-seedance-1.0-lite-t2v)
  DOUBAO_IMAGE_ENDPOINT   选填 - 图像Endpoint ID
  DOUBAO_VIDEO_ENDPOINT   选填 - 视频Endpoint ID
"""

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


# ── 配置 ──────────────────────────────────────────────
BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_IMAGE_MODEL = "doubao-seedream-4-5"
DEFAULT_VIDEO_MODEL = "doubao-seedance-1.0-lite-t2v"


def ensure_api_key():
    key = os.getenv("DOUBAO_API_KEY")
    if not key:
        print(json.dumps({"ok": False, "error": "请设置环境变量 DOUBAO_API_KEY"}))
        sys.exit(1)
    return key


def request_json(method, url, api_key, body=None, timeout=120):
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return {"http_status": resp.status, "body": json.loads(raw) if raw else {}}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        return {"http_status": e.code, "error": f"HTTP {e.code}", "body": raw}
    except Exception as e:
        return {"error": str(e)}


def log(msg, data=None):
    entry = {"message": msg}
    if data is not None:
        entry["data"] = data
    print(json.dumps(entry, ensure_ascii=False), flush=True)


def image_to_file(image_data, output_dir, filename):
    """Save base64 or URL image to file."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, filename)

    try:
        # Case 1: b64_json in response data
        if isinstance(image_data, dict):
            if "b64_json" in image_data and image_data["b64_json"]:
                data = image_data["b64_json"]
                import base64
                with open(path, "wb") as f:
                    f.write(base64.b64decode(data))
                return path
            if "url" in image_data and image_data["url"]:
                return download_file(image_data["url"], path)

        # Case 2: Direct URL string
        if isinstance(image_data, str):
            if image_data.startswith("http"):
                return download_file(image_data, path)
            if image_data.startswith("data:"):
                # Data URI - extract and decode base64
                import base64
                _, encoded = image_data.split(",", 1)
                with open(path, "wb") as f:
                    f.write(base64.b64decode(encoded))
                return path

    except Exception as e:
        log(f"保存文件失败: {e}")
        return None

    return None


def download_file(url, path):
    """Download a file from URL and save locally."""
    try:
        req = urllib.request.Request(url, method="GET", headers={
            "User-Agent": "WeiMeiAIPro/1.0"
        })
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = resp.read()
        with open(path, "wb") as f:
            f.write(data)
        log("文件下载完成", {"path": path, "bytes": len(data)})
        return path
    except Exception as e:
        log(f"下载失败: {e}")
        return None


# ═══════════════════════════════════════════════════════
# STEP 1: 真人照片 → 3D大理石雕塑图
# ═══════════════════════════════════════════════════════
def step1_generate_sculpture(api_key, input_image_path, output_dir,
                              model=None, endpoint_id=None):
    """Transform real person photo into 3D marble sculpture."""
    log("STEP1 开始: 真人照片 → 3D大理石雕塑")

    # Read image and encode to base64
    with open(input_image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")

    model_or_ep = endpoint_id or os.getenv("DOUBAO_IMAGE_ENDPOINT") or model or os.getenv("DOUBAO_DEFAULT_IMAGE_MODEL") or DEFAULT_IMAGE_MODEL

    prompt = (
        "Transform this person into a classical white Carrara marble bust sculpture, "
        "museum quality, photorealistic 3D render, refined facial features, "
        "smooth marble skin with subtle veining, soft flowing hair sculpted in marble, "
        "pink-tinted marble lips, dark cinematic background with warm golden highlights, "
        "half-bust composition on a museum pedestal, ultra detailed 8K"
    )

    body = {
        "model": model_or_ep,
        "prompt": prompt,
        "size": "1024x1024",
        "image_url": f"data:image/jpeg;base64,{image_b64}",
    }

    result = request_json("POST", f"{BASE_URL}/images/generations", api_key, body, timeout=120)

    if result.get("http_status") == 200:
        resp_body = result.get("body", {})
        data_list = resp_body.get("data", [])
        if data_list and len(data_list) > 0:
            image_data = data_list[0]
            path = image_to_file(image_data, output_dir, "sculpture_output.png")
            if path:
                log("STEP1 完成: 雕塑图已生成", {"path": path})
                return path

    # Detailed error
    error_msg = str(result.get("body", result.get("error", "未知错误")))
    log("STEP1 失败", {"detail": error_msg[:200]})
    return None


# ═══════════════════════════════════════════════════════
# STEP 2: 雕塑图 → 旋转视频
# ═══════════════════════════════════════════════════════
def step2_generate_video(api_key, sculpture_image_path, output_dir,
                          model=None, endpoint_id=None):
    """Generate rotating sculpture video from sculpture image."""
    log("STEP2 开始: 雕塑图 → 360°旋转视频")

    # Upload image to a temporary hosting or use base64
    with open(sculpture_image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")

    model_or_ep = endpoint_id or os.getenv("DOUBAO_VIDEO_ENDPOINT") or model or os.getenv("DOUBAO_DEFAULT_VIDEO_MODEL") or DEFAULT_VIDEO_MODEL

    # Build the video prompt with flags
    prompt = (
        "A stunning rotating 3D marble bust sculpture on a museum pedestal, "
        "the sculpture slowly rotates 360 degrees showing front, side and back views, "
        "white Carrara marble with subtle golden highlights, cinematic museum lighting, "
        "dark elegant background with dramatic spotlight, smooth slow rotation, "
        "premium quality"
        " --dur 10 --fps 24 --rs 1080p --ratio 9:16"
    )

    content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
    ]

    body = {"model": model_or_ep, "content": content}
    result = request_json("POST", f"{BASE_URL}/contents/generations/tasks", api_key, body)

    if result.get("http_status") != 200 or not result.get("body", {}).get("id"):
        log("STEP2 提交任务失败", result)
        return None

    task_id = result["body"]["id"]
    log("STEP2 视频任务已提交", {"task_id": task_id})

    # ── 轮询等待 ──
    deadline = time.time() + 600
    attempts = 0
    while time.time() < deadline:
        attempts += 1
        task_result = request_json(
            "GET",
            f"{BASE_URL}/contents/generations/tasks/{urllib.parse.quote(task_id, safe='')}",
            api_key,
        )
        status = task_result.get("body", {}).get("status", "")
        log(f"轮询 {attempts}: status={status}")

        if status == "succeeded":
            video_url = (task_result.get("body", {}).get("content") or {}).get("video_url")
            if video_url:
                # Download the video
                video_path = os.path.join(output_dir, "sculpture_rotation.mp4")
                req = urllib.request.Request(video_url, method="GET")
                with urllib.request.urlopen(req, timeout=300) as resp:
                    video_data = resp.read()
                with open(video_path, "wb") as f:
                    f.write(video_data)
                log("STEP2 完成: 旋转视频已生成", {
                    "path": video_path,
                    "size_bytes": len(video_data),
                    "attempts": attempts,
                })
                return video_path
            log("STEP2 完成但无视频URL", task_result)
            return None

        if status in ("failed", "canceled"):
            log(f"STEP2 任务{status}", task_result)
            return None

        time.sleep(5)

    log("STEP2 超时")
    return None


# ═══════════════════════════════════════════════════════
# 主 管 线
# ═══════════════════════════════════════════════════════
def run_pipeline(input_path, output_dir="./output",
                 image_model=None, video_model=None,
                 image_endpoint=None, video_endpoint=None):
    """Run the full pipeline: photo → sculpture → video."""
    api_key = ensure_api_key()
    os.makedirs(output_dir, exist_ok=True)

    log("管线启动", {"input": input_path, "output": output_dir})

    # STEP 1
    sculpture_path = step1_generate_sculpture(
        api_key, input_path, output_dir,
        model=image_model, endpoint_id=image_endpoint,
    )
    if not sculpture_path:
        log("管线终止: STEP1 失败")
        return {"ok": False, "error": "STEP1 failed"}

    # STEP 2
    video_path = step2_generate_video(
        api_key, sculpture_path, output_dir,
        model=video_model, endpoint_id=video_endpoint,
    )
    if not video_path:
        log("管线终止: STEP2 失败, 雕塑图已保留", {"sculpture": sculpture_path})
        return {"ok": False, "error": "STEP2 failed", "sculpture_path": sculpture_path}

    log("管线完成", {
        "sculpture": sculpture_path,
        "video": video_path,
    })
    return {
        "ok": True,
        "sculpture_path": sculpture_path,
        "video_path": video_path,
    }


# ═══════════════════════════════════════════════════════
# 命 令 行 入 口
# ═══════════════════════════════════════════════════════
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="薇美AI Pro - 3D雕塑视频管线")
    parser.add_argument("--input", required=True, help="输入真人照片路径")
    parser.add_argument("--output", default="./output", help="输出目录")
    parser.add_argument("--image-model", help="图像生成模型")
    parser.add_argument("--video-model", help="视频生成模型")
    parser.add_argument("--image-endpoint", help="图像Endpoint ID")
    parser.add_argument("--video-endpoint", help="视频Endpoint ID")
    args = parser.parse_args()

    result = run_pipeline(
        input_path=args.input,
        output_dir=args.output,
        image_model=args.image_model,
        video_model=args.video_model,
        image_endpoint=args.image_endpoint,
        video_endpoint=args.video_endpoint,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
