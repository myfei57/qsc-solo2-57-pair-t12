"""调节审计。

审计是控制链的最后一环：每次联锁拒绝、每次调质调量、每条越界回滚都写一条记录，
内存保留最近若干条供控制台读取，同时按段落 JSONL 供跨重启回放。
"""

from __future__ import annotations

from .log import AuditLog
from .record import AuditRecord
from .report import summarize
from .timeline import build_timeline

__all__ = ["AuditLog", "AuditRecord", "summarize", "build_timeline"]
