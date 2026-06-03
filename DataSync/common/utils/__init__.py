"""DataSync 使用的公共工具导出。

这里避免在包导入时立即加载可选依赖（例如 `passlib`），
让真正的 DataSync 运行链路只为自己需要的能力付费。
"""

from .converters import convert_numpy_types, safe_float, safe_int
from .market_time import market_now, market_today, market_today_str, MARKET_TIMEZONE


def __getattr__(name: str):
    if name in {"hash_password", "verify_password"}:
        from .crypto import hash_password, verify_password

        exports = {
            "hash_password": hash_password,
            "verify_password": verify_password,
        }
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    # 加密
    "hash_password",
    "verify_password",
    # 类型转换
    "convert_numpy_types",
    "safe_float",
    "safe_int",
    # 市场时间
    "market_now",
    "market_today",
    "market_today_str",
    "MARKET_TIMEZONE",
]
