"""调度控制台 HTTP 服务。

只提供 JSON 接口：状态查询给值班员看现场，动作接口给图形化客户端用。服务用标准
库 ``http.server`` 承载，不引入额外依赖；每个接口都是对平台公开方法的一次调用。
"""

from __future__ import annotations

from .api import Api
from .router import Route, Router
from .server import ConsoleServer, probe_endpoints

__all__ = ["Api", "ConsoleServer", "Route", "Router", "probe_endpoints"]
