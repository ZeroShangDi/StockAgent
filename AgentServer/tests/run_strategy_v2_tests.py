#!/usr/bin/env python3
"""Strategy V2 全面测试脚本 — 在 Docker 环境内运行"""
import json, time, urllib.request, urllib.error, ssl, sys

BASE = "http://localhost:8000/api/v1"
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
        with urllib.request.urlopen(req, timeout=180, context=ctx) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read()
        try:
            return e.code, json.loads(body)
        except:
            return e.code, {"detail": str(body)}
    except Exception as e:
        return 0, {"error": str(e)}

def unwrap(data):
    """Unwrap {'items': [...]} or {'item': {...}} dict responses"""
    if isinstance(data, dict):
        if "items" in data:
            return data["items"]
        if "item" in data:
            return data["item"]
    return data

def login():
    import urllib.parse
    data = urllib.parse.urlencode({"username": "admin", "password": "password123"}).encode()
    req = urllib.request.Request(f"{BASE}/auth/login", data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
        return json.loads(resp.read())["access_token"]

def wait_for_run(token, run_id, timeout_sec=300):
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        _, data = api("GET", f"/strategy-v2/runs/{run_id}", token=token)
        data = unwrap(data)
        if isinstance(data, dict):
            rs = data.get("run_status", "")
            if rs in ("success", "failed", "cancelled"):
                return rs, data
        time.sleep(3)
    return "timeout", {}

def test_all():
    results = []
    print("=" * 60)
    print("Strategy V2 全面测试")
    print("=" * 60)

    try:
        token = login()
        print("✓ 登录成功")
    except Exception as e:
        print(f"✗ 登录失败: {e}")
        return False

    # Get all tasks
    _, tasks_raw = api("GET", "/strategy-v2/tasks", token=token)
    tasks = unwrap(tasks_raw)
    if not isinstance(tasks, list):
        print(f"✗ 获取任务列表格式异常: {type(tasks)}")
        return False

    print(f"✓ 获取到 {len(tasks)} 个任务\n")

    # === T1: 调度器基础 ===
    print("=" * 40)
    print("T1: 调度器基础检查")
    print("=" * 40)
    for t in tasks:
        schedule = t.get("schedule", {}) or {}
        slot = schedule.get("slot", "none")
        mode = schedule.get("mode", "none")
        fire_key = t.get("last_scheduled_fire_key", "")
        last_run = t.get("last_scheduled_run_at", "")
        print(f"  {t['name']}: slot={slot}, mode={mode}, fire_key={fire_key[:40]}...")

        if mode == "scheduled" and slot:
            results.append(("T1-schedule", "pass", f"{t['name']}: slot={slot}"))
        elif mode == "scheduled":
            results.append(("T1-schedule", "fail", f"{t['name']}: 调度模式但无 slot"))
        else:
            results.append(("T1-schedule", "pass", f"{t['name']}: 手动模式"))

    # === T2: 评估器正确性 - 手动触发 ===
    print("\n" + "=" * 40)
    print("T2: 评估器正确性 - 手动触发任务")
    print("=" * 40)

    # Test only non-Coze tasks (Coze all_market tasks take 25+ min)
    non_coze = [t for t in tasks if t.get("strategy_key") != "one_line_stock_picker"]
    test_order = non_coze
    print(f"  跳过 Coze 任务（耗时过长），测试 {len(test_order)} 个非 Coze 任务")

    for task in test_order:
        task_id = task["task_id"]
        name = task["name"]
        strategy = task.get("strategy_key", "")
        scope = task.get("target_scope", {}) or {}
        scope_type = scope.get("scope_type", "?")

        print(f"\n--- {name} ({strategy}, {scope_type}) ---")

        # Trigger
        status, run_data = api("POST", f"/strategy-v2/tasks/{task_id}/runs", token=token)
        if status not in (200, 201):
            detail = run_data.get("detail", str(run_data)[:100]) if isinstance(run_data, dict) else str(run_data)[:100]
            print(f"  ✗ 触发失败: HTTP {status} - {detail}")
            results.append((f"T2-{strategy}", "fail", f"{name}: 触发失败 {status}"))
            continue

        run_id = run_data.get("run_id", "")
        print(f"  触发成功: run_id={run_id[:20]}...")

        # Wait for completion - longer timeout for Coze tasks (all_market = 25+ min)
        timeout = 600 if strategy == "one_line_stock_picker" else 120
        run_status, run_detail = wait_for_run(token, run_id, timeout_sec=timeout)

        if isinstance(run_detail, dict):
            total = run_detail.get("total", 0)
            positive = run_detail.get("positive", 0)
            negative = run_detail.get("negative", 0)
            neutral = run_detail.get("neutral", 0)
            summary = run_detail.get("summary", "")
            error = run_detail.get("error", "")
            print(f"  status={run_status}, targets={total}, +{positive} / -{negative} / 0{neutral}")

            if run_status == "success":
                results.append((f"T2-{strategy}-run", "pass", f"{name}: {summary}"))
                if total == 0:
                    results.append((f"T3-targets", "warn", f"{name}: 0 targets (scope={scope_type})"))
                elif positive > 0:
                    results.append((f"T2-{strategy}-signal", "pass", f"{name}: {positive} 正向信号"))
            elif run_status == "failed":
                results.append((f"T2-{strategy}-run", "fail", f"{name}: {error or summary}"))
            elif run_status == "timeout":
                results.append((f"T2-{strategy}-timeout", "fail", f"{name}: 超时 >{timeout}s"))

        # Check items for data source info
        _, items_raw = api("GET", f"/strategy-v2/runs/{run_id}/items?limit=3", token=token)
        items = unwrap(items_raw)
        if isinstance(items, list) and items:
            for item in items[:2]:
                meta = item.get("meta", {}) or {}
                data_source = meta.get("data_source", "N/A")
                ts = meta.get("timestamp", "N/A")
                print(f"    signal={item.get('signal')}, source={data_source}")

                if strategy in ("intraday_price_move", "position_intraday_pnl", "price_change"):
                    if data_source and data_source != "stock_daily" and data_source != "N/A":
                        results.append((f"T2-{strategy}-realtime", "pass", f"{name}: 实时行情 source={data_source}"))
                    elif data_source == "stock_daily":
                        results.append((f"T2-{strategy}-realtime", "warn", f"{name}: 回退到日线数据"))
            else:
                print(f"    (无 items)")

        # Check actions
        _, audits_raw = api("GET", f"/strategy-v2/runs/{run_id}/action-audits", token=token)
        audits = unwrap(audits_raw)
        if isinstance(audits, list):
            executed = sum(1 for a in audits if a.get("status") == "executed")
            skipped = sum(1 for a in audits if a.get("status") == "skipped")
            failed = sum(1 for a in audits if a.get("status") == "failed")
            print(f"    actions: {len(audits)} total, {executed} exec, {skipped} skip, {failed} fail")
            if positive > 0 and executed == 0 and total > 0:
                results.append(("T5-notify", "warn", f"{name}: 有正向信号{positive}但无 executed actions"))

    # === T3: 数据完整性 ===
    print("\n" + "=" * 40)
    print("T3: 数据完整性")
    print("=" * 40)
    for task in tasks:
        task_id = task["task_id"]
        _, runs_raw = api("GET", f"/strategy-v2/tasks/{task_id}/runs?limit=2", token=token)
        runs = unwrap(runs_raw)
        if isinstance(runs, list) and runs:
            latest = runs[0]
            rs = latest.get("run_status", "?")
            print(f"  {task['name']}: latest_run={rs}")
            # Check for MongoDB _id leak (top-level _id key, not substring match like "run_id")
            has_oid_key = any(k == "_id" for k in (latest.keys() if isinstance(latest, dict) else []))
            if has_oid_key:
                results.append(("T7-ObjectId", "fail", f"{task['name']}: _id 泄漏"))
            else:
                results.append(("T7-ObjectId", "pass", f"{task['name']}: 序列化正常"))

    # === T4: 通知系统 ===
    print("\n" + "=" * 40)
    print("T4: 通知系统")
    print("=" * 40)
    _, subs_raw = api("GET", "/strategy/subscriptions", token=token)
    subs = unwrap(subs_raw)
    if isinstance(subs, list):
        print(f"  订阅数: {len(subs)}")
        for s in subs:
            print(f"    strategy={s.get('strategy_key','?')}, status={s.get('status','?')}")
    else:
        print(f"  订阅响应异常: {type(subs)}")

    # === Summary ===
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    passes = sum(1 for r in results if r[1] == "pass")
    fails = sum(1 for r in results if r[1] == "fail")
    warns = sum(1 for r in results if r[1] == "warn")
    print(f"  PASS: {passes}  FAIL: {fails}  WARN: {warns}")
    for r in results:
        flag = {"pass": "✓", "fail": "✗", "warn": "⚠"}.get(r[1], "?")
        print(f"  {flag} [{r[0]}] {r[2]}")

    return fails == 0

if __name__ == "__main__":
    ok = test_all()
    sys.exit(0 if ok else 1)
