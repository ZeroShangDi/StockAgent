"""
StockAgent 统一入口

根据环境变量 NODE_TYPE 启动对应节点:
- web: Web 网关节点
- data_sync: 数据同步节点
- mcp: MCP 服务节点
- inference: 分析智能体节点
- listener: 实时监听节点
- backtest: 量化回测节点

使用方式:
    # 启动 Web 节点
    NODE_TYPE=web python main.py

    # 一键启动完整开发栈
    python main.py --all

    # 启动标准开发栈
    python main.py --all --profile standard
    
    # 启动数据同步节点
    NODE_TYPE=data_sync python main.py
    
    # 启动推理节点 (可启动多个)
    NODE_TYPE=inference MAX_CONCURRENT_TASKS=10 python main.py
    
    # 启动监听节点
    NODE_TYPE=listener python main.py
    
    # 启动回测节点
    NODE_TYPE=backtest python main.py
"""

import asyncio
import argparse
import os
import sys
import subprocess

from core.settings import settings
from core.protocols import NodeType
from src.config import config_manager


def _create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="StockAgent 统一启动入口")
    parser.add_argument(
        "--node-type",
        dest="node_type",
        help="指定要启动的节点类型，如 web / data_sync / inference / listener / backtest",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="一键启动开发栈，默认使用 full 档位",
    )
    parser.add_argument(
        "--profile",
        choices=["lite", "standard", "full"],
        default="full",
        help="开发栈档位：lite=轻量开发，standard=常用页面完整，full=全部节点",
    )
    parser.add_argument(
        "--nodes",
        help="配合 --all 使用，自定义要启动的节点列表，逗号分隔；指定后会覆盖 profile 默认节点",
    )
    parser.add_argument(
        "--include-backtest",
        action="store_true",
        help="配合 --all 使用，同时启动 backtest 节点",
    )
    parser.add_argument(
        "--include-mcp",
        action="store_true",
        help="配合 --all 使用，同时启动 mcp 节点",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="开发模式下为 web 节点开启热更新；单独启动 web 或配合 --all 时生效",
    )
    return parser


def _run_web_reload() -> int:
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "nodes.web.app:create_app",
        "--factory",
        "--host",
        settings.web.host,
        "--port",
        str(settings.web.port),
        "--reload",
    ]
    completed = subprocess.run(command, check=False)
    return completed.returncode


def main():
    """主入口"""
    args = _create_parser().parse_args()

    # 加载 YAML 配置
    config_count = config_manager.load()
    print(f"Loaded {config_count} YAML config files from {config_manager.config_dir}")

    if args.all:
        from src.dev_stack import run_dev_stack

        return run_dev_stack(
            nodes=args.nodes,
            profile=args.profile,
            include_backtest=args.include_backtest,
            include_mcp=args.include_mcp,
            reload_web=(args.reload or settings.web.reload),
        )

    # 从环境变量或配置获取节点类型
    node_type_str = args.node_type or os.environ.get("NODE_TYPE", settings.node.node_type)

    if node_type_str == "all":
        from src.dev_stack import run_dev_stack

        return run_dev_stack(
            nodes=args.nodes,
            profile=args.profile,
            include_backtest=args.include_backtest,
            include_mcp=args.include_mcp,
            reload_web=(args.reload or settings.web.reload),
        )

    try:
        node_type = NodeType(node_type_str)
    except ValueError:
        print(f"Invalid NODE_TYPE: {node_type_str}")
        print(f"Valid types: {[t.value for t in NodeType]}")
        sys.exit(1)
    
    print(f"Starting {node_type.value} node...")

    if node_type == NodeType.WEB and (args.reload or settings.web.reload):
        print("Starting web node in reload mode...")
        sys.exit(_run_web_reload())
    
    # 根据节点类型创建并启动节点
    if node_type == NodeType.WEB:
        from nodes.web.node import WebNode
        node = WebNode()
        
    elif node_type == NodeType.DATA_SYNC:
        from nodes.data_sync.node import DataSyncNode
        node = DataSyncNode()
        
    elif node_type == NodeType.MCP:
        from nodes.mcp.node import MCPNode
        node = MCPNode()
        
    elif node_type == NodeType.INFERENCE:
        from nodes.inference.node import InferenceNode
        max_tasks = int(os.environ.get("MAX_CONCURRENT_TASKS", 5))
        node = InferenceNode(max_concurrent_tasks=max_tasks)
    
    elif node_type == NodeType.LISTENER:
        from nodes.listener.node import ListenerNode
        node = ListenerNode()
    
    elif node_type == NodeType.BACKTEST:
        from nodes.backtest_engine.node import BacktestNode
        node = BacktestNode()
        
    else:
        print(f"Unknown node type: {node_type}")
        sys.exit(1)
    
    # 运行节点
    try:
        asyncio.run(node.main())
    except KeyboardInterrupt:
        print("\nShutdown by user")
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
