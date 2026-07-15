#!/usr/bin/env python3
"""
薇美AI Pro — AI请求队列处理器
当用户在网站提交了AI生成请求后，运行此脚本处理所有待办请求

使用方式：
  1. 用户网站在 repo 的 data/queue/ 下生成请求文件
  2. 运行 python process_queue.py 处理所有待办
  3. 结果写入 data/results/，网站自动读取
"""
import json, base64, os, time, uuid

WORK_DIR = os.path.dirname(os.path.abspath(__file__))
QUEUE_DIR = os.path.join(WORK_DIR, "data", "queue")
RESULT_DIR = os.path.join(WORK_DIR, "data", "results")
os.makedirs(QUEUE_DIR, exist_ok=True)
os.makedirs(RESULT_DIR, exist_ok=True)


def scan_queue():
    """扫描待办队列"""
    if not os.path.isdir(QUEUE_DIR):
        return []
    tasks = []
    for f in sorted(os.listdir(QUEUE_DIR)):
        if f.endswith(".json") and not f.startswith("."):
            try:
                with open(os.path.join(QUEUE_DIR, f), "r") as fp:
                    task = json.load(fp)
                    task["_file"] = f
                    tasks.append(task)
            except: pass
    return tasks


def complete_task(task, result_data):
    """完成任务，写入结果"""
    task_id = task.get("id", str(uuid.uuid4().hex[:8]))
    result = {
        "id": task_id,
        "type": task.get("type", "image"),
        "prompt": task.get("prompt", ""),
        "status": "completed",
        "result": result_data,
        "completed_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    with open(os.path.join(RESULT_DIR, f"{task_id}.json"), "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    # 删除队列文件
    try:
        os.remove(os.path.join(QUEUE_DIR, task["_file"]))
    except: pass
    return result


def fail_task(task, error):
    """标记失败"""
    task_id = task.get("id", str(uuid.uuid4().hex[:8]))
    result = {
        "id": task_id,
        "type": task.get("type", "image"),
        "prompt": task.get("prompt", ""),
        "status": "failed",
        "error": error,
        "completed_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    with open(os.path.join(RESULT_DIR, f"{task_id}.json"), "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    try:
        os.remove(os.path.join(QUEUE_DIR, task["_file"]))
    except: pass


def main():
    print(f"薇美AI Pro — 请求队列处理器")
    print(f"队列目录: {QUEUE_DIR}")
    print(f"结果目录: {RESULT_DIR}")
    print()

    tasks = scan_queue()
    if not tasks:
        print("📭 暂无待处理请求")
        return

    print(f"📋 发现 {len(tasks)} 个待处理请求:\n")

    for i, task in enumerate(tasks, 1):
        task_type = task.get("type", "未知")
        prompt = task.get("prompt", "")[:50]
        has_image = "有图片" if task.get("image") else "纯文字"
        print(f"  [{i}/{len(tasks)}] {task_type} | {prompt}... | {has_image}")

    print(f"\n请到对话中告诉小薇：")
    print(f"  「处理 {len(tasks)} 个待办请求」")
    print(f"\n小薇会依次调用 ImageGen/VideoGen 处理，结果自动存回仓库\n")


if __name__ == "__main__":
    main()
