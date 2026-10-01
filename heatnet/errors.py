"""平台统一异常类型。

现场要区分四类失败：动作顺序或联锁条件不满足（条件满足即可继续）、机械位置
超差（没对到位，需要重新定位）、配置或持久化失败（装配期就该拦下的接线问题）、
以及命名空间解析失败。审计流水按异常类型落盘，巡检时才能一眼区分"条件没到"、
"没对好位"和"接线不对"。
"""

from __future__ import annotations


class PlantError(Exception):
    """所有平台异常的基类，携带出错的组件名。"""

    def __init__(self, message: str, *, component: str = "plant") -> None:
        super().__init__(message)
        self.message = message
        self.component = component

    def as_record(self) -> dict:
        """转成审计流水可以直接落盘的一条记录。"""

        return {
            "type": type(self).__name__,
            "component": self.component,
            "message": self.message,
        }


class InterlockError(PlantError):
    """顺序或联锁条件不满足，动作被拒绝。"""


class AlignmentError(PlantError):
    """机械位置超出对齐公差。"""


class StorageError(PlantError):
    """持久化读写失败。"""


class ConfigError(PlantError):
    """配置缺失或取值非法。"""


class NamespaceError(PlantError):
    """命名空间重复注册或解析失败。"""


class ForecastError(PlantError):
    """气象预报越界或曲线过期，禁止据此调质。"""
