"""
本地开发栈一键启动器

预设档位:
- lite: web / inference / listener
- standard: web / data_sync / inference / listener / backtest
- full: web / data_sync / inference / listener / backtest / mcp

使用方式:
    python main.py --all
    python main.py --all --profile standard
    python main.py --all --nodes web,data_sync,listener
    python main.py --all --reload
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Iterable


DEV_STACK_PROFILES = {
    "lite": ("web", "inference", "listener"),
    "standard": ("web", "data_sync", "inference", "listener", "backtest"),
    "full": ("web", "data_sync", "inference", "listener", "backtest", "mcp"),
}
DEFAULT_PROFILE = "full"
OPTIONAL_NODES = ("backtest", "mcp")
VALID_NODES = set().union(*DEV_STACK_PROFILES.values()) | set(OPTIONAL_NODES)


class DevStackRunner:
    def __init__(self, nodes: Iterable[str], reload_web: bool = False):
        self.nodes = tuple(nodes)
        self.reload_web = reload_web
        self.repo_root = Path(__file__).resolve().parents[1]
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def run(self) -> int:
        self._install_signal_handlers()

        if not self.nodes:
            print("未指定任何节点，已取消启动")
            return 1

        print(f"一键启动节点: {', '.join(self.nodes)}")

        try:
            for node in self.nodes:
                self._start_node(node)

            return self._wait_for_children()
        finally:
            self._shutdown_all()

    def _install_signal_handlers(self) -> None:
        def _handler(signum, _frame):
            if self._stop_event.is_set():
                return
            signame = signal.Signals(signum).name
            print(f"\n收到 {signame}，正在停止全部节点...")
            self._stop_event.set()
            self._shutdown_all()

        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGTERM, _handler)

    def _start_node(self, node: str) -> None:
        env = os.environ.copy()
        env["NODE_TYPE"] = node
        env.pop("PYTHONEXECUTABLE", None)

        if node == "web" and self.reload_web:
            command = [
                sys.executable,
                "-m",
                "uvicorn",
                "nodes.web.app:create_app",
                "--factory",
                "--host",
                env.get("WEB_HOST", "0.0.0.0"),
                "--port",
                env.get("WEB_PORT", "8000"),
                "--reload",
            ]
        else:
            command = [sys.executable, "main.py", "--node-type", node]
        process = subprocess.Popen(
            command,
            cwd=self.repo_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )

        self._processes[node] = process
        threading.Thread(
            target=self._stream_output,
            args=(node, process),
            daemon=True,
        ).start()

        print(f"[manager] 已启动 {node}，PID={process.pid}")

    def _stream_output(self, node: str, process: subprocess.Popen[str]) -> None:
        assert process.stdout is not None
        for line in process.stdout:
            print(f"[{node}] {line.rstrip()}")

    def _wait_for_children(self) -> int:
        while not self._stop_event.is_set():
            for node, process in list(self._processes.items()):
                return_code = process.poll()
                if return_code is None:
                    continue

                if self._stop_event.is_set():
                    return 0

                self._stop_event.set()
                if return_code == 0:
                    print(f"[manager] {node} 已退出，正在停止其余节点...")
                else:
                    print(f"[manager] {node} 异常退出，退出码={return_code}，正在停止其余节点...")
                self._shutdown_all(exclude=node)
                return return_code

            time.sleep(0.5)

        return 0

    def _shutdown_all(self, exclude: str | None = None) -> None:
        with self._lock:
            for node, process in self._processes.items():
                if node == exclude:
                    continue
                if process.poll() is not None:
                    continue
                self._terminate_process_group(node, process)

            deadline = time.time() + 8
            for node, process in self._processes.items():
                if node == exclude:
                    continue
                if process.poll() is not None:
                    continue
                while time.time() < deadline and process.poll() is None:
                    time.sleep(0.2)
                if process.poll() is None:
                    self._kill_process_group(node, process)

    def _terminate_process_group(self, node: str, process: subprocess.Popen[str]) -> None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            print(f"[manager] 正在停止 {node}...")
        except ProcessLookupError:
            return

    def _kill_process_group(self, node: str, process: subprocess.Popen[str]) -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
            print(f"[manager] {node} 停止超时，已强制结束")
        except ProcessLookupError:
            return


def resolve_nodes(
    nodes: str | None,
    profile: str,
    include_backtest: bool,
    include_mcp: bool,
) -> list[str]:
    if nodes:
        resolved = [item.strip() for item in nodes.split(",") if item.strip()]
    else:
        if profile not in DEV_STACK_PROFILES:
            valid_profiles = ", ".join(DEV_STACK_PROFILES)
            raise ValueError(f"无效开发档位: {profile}；可选值: {valid_profiles}")
        resolved = list(DEV_STACK_PROFILES[profile])

    if include_backtest and "backtest" not in resolved:
        resolved.append("backtest")
    if include_mcp and "mcp" not in resolved:
        resolved.append("mcp")

    invalid = [node for node in resolved if node not in VALID_NODES]
    if invalid:
        valid = ", ".join(sorted(VALID_NODES))
        raise ValueError(f"无效节点类型: {', '.join(invalid)}；可选值: {valid}")

    return resolved


def run_dev_stack(
    nodes: str | None = None,
    profile: str = DEFAULT_PROFILE,
    include_backtest: bool = False,
    include_mcp: bool = False,
    reload_web: bool = False,
) -> int:
    runner = DevStackRunner(
        resolve_nodes(nodes, profile, include_backtest, include_mcp),
        reload_web=reload_web,
    )
    return runner.run()


def main() -> None:
    exit_code = run_dev_stack()
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
