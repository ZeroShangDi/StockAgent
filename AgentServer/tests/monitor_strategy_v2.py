#!/usr/bin/env python3
"""Strategy V2 系统监控脚本 — 持续检查运行状态"""
import json, time, urllib.request, urllib.error, ssl, sys
from datetime import datetime, timezone

BASE = "http://localhost:8000/api/v1"
CHECK_INTERVAL = 300  # 5 minutes between checks

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def api(method, path, body=None, token=None):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
            return resp.status, json.loads(resp.read())
    except Exception as e:
        return 0, {"error": str(e)}

def login():
    import urllib.parse
    data = urllib.parse.urlencode({"username": "admin", "password": "password123"}).encode()
    req = urllib.request.Request(f"{BASE}/auth/login", data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
        return json.loads(resp.read())["access_token"]

def unwrap(data):
    if isinstance(data, dict):
        if "items" in data: return data["items"]
        if "item" in data: return data["item"]
    return data

def check_system(token):
    issues = []
    now = datetime.now(timezone.utc)
    print(f"\n{'='*50}")
    print(f"系统检查 - {now.isoformat()}")
    print(f"{'='*50}")

    # 1. Health check
    try:
        with urllib.request.urlopen(f"http://localhost:8000/health", timeout=5, context=ctx) as resp:
            print("✓ 健康检查通过")
    except Exception as e:
        issues.append(f"健康检查失败: {e}")
        print(f"✗ 健康检查失败: {e}")
        return issues

    # 2. Check all tasks
    _, tasks_raw = api("GET", "/strategy-v2/tasks", token=token)
    tasks = unwrap(tasks_raw)
    if not isinstance(tasks, list):
        issues.append("无法获取任务列表")
        return issues

    for t in tasks:
        name = t.get("name", "?")
        strategy = t.get("strategy_key", "?")
        scope = (t.get("target_scope") or {})
        scope_type = scope.get("scope_type", "?")
        schedule = (t.get("schedule") or {})
        slot = schedule.get("slot", "")
        mode = schedule.get("mode", "")

        # 3. Check for stale/failed runs
        _, runs_raw = api("GET", f"/strategy-v2/tasks/{t['task_id']}/runs?limit=2", token=token)
        runs = unwrap(runs_raw)
        if isinstance(runs, list) and runs:
            latest = runs[0]
            rs = latest.get("run_status", "")
            if rs == "failed":
                error = latest.get("error", latest.get("summary", ""))
                issues.append(f"{name}: 最近运行失败 - {error[:80]}")
                print(f"  ⚠ {name}: FAILED - {error[:80]}")
            elif rs == "running":
                started = latest.get("started_at", "")
                print(f"  ⟳ {name}: RUNNING (started={started})")
            else:
                print(f"  ✓ {name}: {rs} ({latest.get('total',0)} targets)")

        # 4. Check schedule status
        if mode == "scheduled":
            last_fire = t.get("last_scheduled_fire_key", "")
            last_run = t.get("last_scheduled_run_at", "")
            print(f"    schedule: slot={slot}, last_run={last_run}")

    # 5. Check MongoDB connectivity (via task query success)
    print(f"\n  总任务数: {len(tasks)}, 问题数: {len(issues)}")
    return issues

def main():
    print("Strategy V2 持续监控启动")
    try:
        token = login()
        print("✓ 登录成功")
    except Exception as e:
        print(f"✗ 登录失败: {e}")
        return

    all_issues = []
    iteration = 0
    while True:
        iteration += 1
        try:
            token = login()  # refresh token
        except Exception:
            pass

        issues = check_system(token)
        all_issues.extend(issues)

        if issues:
            print(f"\n⚠ 发现 {len(issues)} 个问题: ")
            for i in issues[-5:]:
                print(f"  - {i}")

        print(f"\n第 {iteration} 轮检查完成, {CHECK_INTERVAL}s 后继续...")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
