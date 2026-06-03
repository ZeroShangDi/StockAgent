"""DataSync 公共导出。

保持接口兼容，但尽量避免顶层导入时立即拉起不必要的可选依赖。
"""

from common.utils.converters import convert_numpy_types, safe_float, safe_int


def __getattr__(name: str):
    if name in {"get_logger", "setup_loki_handler"}:
        from common.logger import get_logger, setup_loki_handler

        exports = {
            "get_logger": get_logger,
            "setup_loki_handler": setup_loki_handler,
        }
        return exports[name]

    if name in {"hash_password", "verify_password"}:
        from common.utils.crypto import hash_password, verify_password

        exports = {
            "hash_password": hash_password,
            "verify_password": verify_password,
        }
        return exports[name]

    if name == "enums":
        from common import enums

        return enums

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    # 日志
    "get_logger",
    "setup_loki_handler",
    # 工具函数
    "hash_password",
    "verify_password",
    "convert_numpy_types",
    "safe_float",
    "safe_int",
    # 枚举
    "enums",
]
