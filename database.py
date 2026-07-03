"""
数据库连接管理模块
提供上下文管理器，替代之前裸 conn.close() 的模式，
确保异常时连接也能被正确关闭。
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

DB_PATH = str(Path(__file__).resolve().parent / "barber.db")


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    """获取数据库连接的上下文管理器，退出时自动关闭连接。

    用法:
        with get_db() as conn:
            rows = conn.execute("SELECT ...").fetchall()
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
