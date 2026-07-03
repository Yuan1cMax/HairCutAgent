"""
测试夹具：内存数据库 + TestClient

通过临时文件隔离测试数据，每个测试独立运行。
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

# ── 模块路径 ──────────────────────────────────────────────
SRC_DIR = Path(__file__).resolve().parent.parent


def _init_db(db_path: str) -> None:
    """手动初始化测试数据库（等价于 main.py 的 startup 事件）"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 建表
    cursor.execute("""CREATE TABLE IF NOT EXISTS designers (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
        specialty TEXT, status TEXT DEFAULT 'active', is_available INTEGER DEFAULT 1)""")

    cursor.execute("""CREATE TABLE IF NOT EXISTS slots (
        id INTEGER PRIMARY KEY AUTOINCREMENT, designer_id INTEGER NOT NULL,
        date TEXT NOT NULL, time TEXT NOT NULL, is_booked INTEGER DEFAULT 0,
        FOREIGN KEY (designer_id) REFERENCES designers(id))""")

    cursor.execute("""CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT, designer_id INTEGER NOT NULL,
        slot_id INTEGER NOT NULL, customer_name TEXT, customer_phone TEXT,
        service TEXT, store TEXT, date TEXT NOT NULL, time TEXT NOT NULL,
        status TEXT DEFAULT 'active', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (designer_id) REFERENCES designers(id),
        FOREIGN KEY (slot_id) REFERENCES slots(id))""")

    cursor.execute("""CREATE TABLE IF NOT EXISTS services (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
        price REAL NOT NULL, duration_minutes INTEGER NOT NULL,
        is_active INTEGER DEFAULT 1)""")

    cursor.execute("""CREATE TABLE IF NOT EXISTS business_hours (
        id INTEGER PRIMARY KEY AUTOINCREMENT, store_name TEXT NOT NULL,
        open_time TEXT NOT NULL, close_time TEXT NOT NULL,
        break_start TEXT, break_end TEXT, weekly_off TEXT DEFAULT '[0]',
        holidays TEXT DEFAULT '[]', is_active INTEGER DEFAULT 1)""")

    # 种子数据 — 营业配置
    cursor.execute("""INSERT INTO business_hours (
        store_name, open_time, close_time, break_start, break_end, weekly_off, holidays, is_active
    ) VALUES ('西湖店', '09:00', '21:00', '12:00', '13:00', '[0]',
        '["2026-01-01","2026-05-01"]', 1)""")

    # 种子数据 — 服务
    cursor.executemany(
        "INSERT INTO services (name, price, duration_minutes, is_active) VALUES (?,?,?,?)",
        [("洗剪吹", 68.0, 60, 1), ("烫发", 268.0, 180, 1)],
    )

    # 种子数据 — 设计师 + slots
    cursor.execute(
        "INSERT INTO designers (name, specialty, status, is_available) VALUES (?,?,?,?)",
        ("测试发型师小王", "短发造型", "active", 1),
    )
    designer_id = cursor.lastrowid

    slot_times = [
        "09:00", "09:30", "10:00", "10:30", "11:00", "11:30",
        "13:00", "13:30", "14:00", "14:30", "15:00",
    ]
    today = datetime.now()
    for day in range(14):
        date = (today + timedelta(days=day)).strftime("%Y-%m-%d")
        for t in slot_times:
            cursor.execute(
                "INSERT INTO slots (designer_id, date, time, is_booked) VALUES (?,?,?,0)",
                (designer_id, date, t),
            )

    conn.commit()
    conn.close()


@pytest.fixture
def test_db() -> Generator[str, None, None]:
    """创建独立测试数据库，测试结束后清理"""
    db_path = str(SRC_DIR / "_test_barber.db")
    # 确保干净起点
    if os.path.exists(db_path):
        os.remove(db_path)
    _init_db(db_path)
    yield db_path
    if os.path.exists(db_path):
        os.remove(db_path)


@pytest.fixture
def client(test_db: str, monkeypatch) -> Generator[TestClient, None, None]:
    """注入测试数据库路径后，返回 TestClient"""
    import database
    monkeypatch.setattr(database, "DB_PATH", test_db)
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")

    import main
    # 清除 FastAPI 依赖覆盖，确保每次干净
    main.app.dependency_overrides.clear()

    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def admin_token() -> str:
    return "test-admin-token"


@pytest.fixture
def admin_headers(admin_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {admin_token}"}
