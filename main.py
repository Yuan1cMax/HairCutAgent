"""
理发店预约系统后端 API
端口: 8003
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from auth import require_admin
from database import get_db


app = FastAPI(title="理发店预约系统")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# ==================== 默认营业规则（迁移兜底） ====================
DEFAULT_BUSINESS_HOURS = {"start": "09:00", "end": "21:00"}
DEFAULT_LUNCH_BREAK = {"start": "12:00", "end": "13:00"}
DEFAULT_HOLIDAYS = [
    "2026-01-01",
    "2026-01-29",
    "2026-01-30",
    "2026-01-31",
    "2026-02-01",
    "2026-02-02",
    "2026-04-05",
    "2026-05-01",
    "2026-05-02",
    "2026-05-03",
    "2026-06-01",
    "2026-09-27",
    "2026-10-01",
    "2026-10-02",
    "2026-10-03",
]
DEFAULT_REST_DAYS = []
DEFAULT_STORE_NAME = "西湖店"
DEFAULT_SLOT_TIMES = [
    "09:00",
    "09:30",
    "10:00",
    "10:30",
    "11:00",
    "11:30",
    "13:00",
    "13:30",
    "14:00",
    "14:30",
    "15:00",
    "15:30",
    "16:00",
    "16:30",
    "17:00",
    "17:30",
    "18:00",
    "18:30",
    "19:00",
    "19:30",
    "20:00",
]


def parse_json_array(value: Optional[str], fallback: list[Any]) -> list[Any]:
    if not value:
        return fallback
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else fallback
    except json.JSONDecodeError:
        return fallback


def time_to_minutes(time_str: str) -> int:
    hours, minutes = map(int, time_str.split(":"))
    return hours * 60 + minutes


def is_time_in_range(time_str: str, start: str, end: str) -> bool:
    current = time_to_minutes(time_str)
    return time_to_minutes(start) <= current < time_to_minutes(end)


def get_business_config(store_name: Optional[str] = None) -> dict[str, Any]:
    target_store = store_name or DEFAULT_STORE_NAME
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT * FROM business_hours
            WHERE store_name = ? AND is_active = 1
            ORDER BY id ASC
            LIMIT 1
            """,
            (target_store,),
        ).fetchone()

        if not row:
            row = conn.execute(
                """
                SELECT * FROM business_hours
                WHERE is_active = 1
                ORDER BY id ASC
                LIMIT 1
                """
            ).fetchone()

    if not row:
        return {
            "store_name": target_store,
            "open_time": DEFAULT_BUSINESS_HOURS["start"],
            "close_time": DEFAULT_BUSINESS_HOURS["end"],
            "break_start": DEFAULT_LUNCH_BREAK["start"],
            "break_end": DEFAULT_LUNCH_BREAK["end"],
            "weekly_off": DEFAULT_REST_DAYS,
            "holidays": DEFAULT_HOLIDAYS,
        }

    return {
        "id": row["id"],
        "store_name": row["store_name"],
        "open_time": row["open_time"],
        "close_time": row["close_time"],
        "break_start": row["break_start"],
        "break_end": row["break_end"],
        "weekly_off": parse_json_array(row["weekly_off"], DEFAULT_REST_DAYS),
        "holidays": parse_json_array(row["holidays"], DEFAULT_HOLIDAYS),
    }


def is_holiday(date_str: str, store_name: Optional[str] = None) -> bool:
    config = get_business_config(store_name)
    return date_str in config["holidays"]


def is_rest_day(date_str: str, store_name: Optional[str] = None) -> bool:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return False
    config = get_business_config(store_name)
    return dt.weekday() in config["weekly_off"]


def is_within_business_hours(time_str: str, store_name: Optional[str] = None) -> bool:
    if not time_str:
        return True
    config = get_business_config(store_name)
    if config["break_start"] and config["break_end"]:
        if is_time_in_range(time_str, config["break_start"], config["break_end"]):
            return False
    return is_time_in_range(time_str, config["open_time"], config["close_time"])


def get_slots_for_business_hours(store_name: Optional[str] = None) -> list[str]:
    config = get_business_config(store_name)
    open_minutes = time_to_minutes(config["open_time"])
    close_minutes = time_to_minutes(config["close_time"])
    break_start = config.get("break_start")
    break_end = config.get("break_end")
    slots: list[str] = []

    current = open_minutes
    while current < close_minutes:
        hh = current // 60
        mm = current % 60
        slot = f"{hh:02d}:{mm:02d}"
        if break_start and break_end and is_time_in_range(slot, break_start, break_end):
            current += 30
            continue
        slots.append(slot)
        current += 30
    return slots


def get_alternative_slots(
    date: str,
    store_name: Optional[str] = None,
    exclude_time: Optional[str] = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                s.time,
                d.id AS designer_id,
                d.name AS designer_name
            FROM slots s
            JOIN designers d ON s.designer_id = d.id
            WHERE s.date = ?
              AND s.is_booked = 0
              AND d.status = 'active'
              AND d.is_available = 1
              AND (? IS NULL OR s.time <> ?)
            ORDER BY s.time, d.name
            """,
            (date, exclude_time, exclude_time),
        ).fetchall()

    alternatives: list[dict[str, Any]] = []
    for row in rows:
        alternatives.append(
            {
                "date": date,
                "time": row["time"],
                "designer_id": row["designer_id"],
                "designer_name": row["designer_name"],
                "store": store_name or DEFAULT_STORE_NAME,
            }
        )
        if len(alternatives) >= limit:
            break
    return alternatives


def ensure_column(cursor: sqlite3.Cursor, table: str, column: str, definition: str) -> None:
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    except sqlite3.OperationalError:
        pass


def generate_slots_for_designer(cursor: sqlite3.Cursor, designer_id: int, days: int = 14) -> None:
    today = datetime.now()
    slot_times = get_slots_for_business_hours()
    for day_offset in range(days):
        date = (today + timedelta(days=day_offset)).strftime("%Y-%m-%d")
        for slot_time in slot_times:
            exists = cursor.execute(
                """
                SELECT 1 FROM slots
                WHERE designer_id = ? AND date = ? AND time = ?
                """,
                (designer_id, date, slot_time),
            ).fetchone()
            if not exists:
                cursor.execute(
                    """
                    INSERT INTO slots (designer_id, date, time, is_booked)
                    VALUES (?, ?, ?, 0)
                    """,
                    (designer_id, date, slot_time),
                )


@app.on_event("startup")
def startup() -> None:
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS designers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                specialty TEXT,
                status TEXT DEFAULT 'active'
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS slots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                designer_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                is_booked INTEGER DEFAULT 0,
                FOREIGN KEY (designer_id) REFERENCES designers(id)
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                designer_id INTEGER NOT NULL,
                slot_id INTEGER NOT NULL,
                customer_name TEXT,
                customer_phone TEXT,
                service TEXT,
                store TEXT,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (designer_id) REFERENCES designers(id),
                FOREIGN KEY (slot_id) REFERENCES slots(id)
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                price REAL NOT NULL,
                duration_minutes INTEGER NOT NULL,
                is_active INTEGER DEFAULT 1
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS business_hours (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_name TEXT NOT NULL,
                open_time TEXT NOT NULL,
                close_time TEXT NOT NULL,
                break_start TEXT,
                break_end TEXT,
                weekly_off TEXT DEFAULT '[0]',
                holidays TEXT DEFAULT '[]',
                is_active INTEGER DEFAULT 1
            )
            """
        )

        ensure_column(cursor, "bookings", "service", "TEXT")
        ensure_column(cursor, "bookings", "store", "TEXT")
        ensure_column(cursor, "designers", "is_available", "INTEGER DEFAULT 1")

        cursor.execute("SELECT COUNT(*) FROM business_hours")
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                """
                INSERT INTO business_hours (
                    store_name, open_time, close_time, break_start, break_end, weekly_off, holidays, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    DEFAULT_STORE_NAME,
                    DEFAULT_BUSINESS_HOURS["start"],
                    DEFAULT_BUSINESS_HOURS["end"],
                    DEFAULT_LUNCH_BREAK["start"],
                    DEFAULT_LUNCH_BREAK["end"],
                    json.dumps(DEFAULT_REST_DAYS, ensure_ascii=False),
                    json.dumps(DEFAULT_HOLIDAYS, ensure_ascii=False),
                ),
            )

        cursor.execute("SELECT COUNT(*) FROM services")
        if cursor.fetchone()[0] == 0:
            services = [
                ("洗剪吹", 68.0, 60, 1),
                ("男士剪发", 48.0, 45, 1),
                ("女士剪发", 58.0, 60, 1),
                ("烫发", 268.0, 180, 1),
                ("染发", 238.0, 150, 1),
            ]
            cursor.executemany(
                """
                INSERT INTO services (name, price, duration_minutes, is_active)
                VALUES (?, ?, ?, ?)
                """,
                services,
            )

        cursor.execute("SELECT COUNT(*) FROM designers")
        if cursor.fetchone()[0] == 0:
            designers = [
                ("阿杰", "男士潮流剪发、锡纸烫", "active", 1),
                ("小美", "女士造型、染烫", "active", 1),
                ("老王", "传统剪发、刮脸", "active", 1),
                ("Tony", "韩系造型、空气刘海", "active", 1),
                ("阿强", "男士寸头、复古油头", "active", 1),
            ]
            cursor.executemany(
                """
                INSERT INTO designers (name, specialty, status, is_available)
                VALUES (?, ?, ?, ?)
                """,
                designers,
            )

            designer_ids = cursor.execute("SELECT id FROM designers").fetchall()
            for designer_row in designer_ids:
                generate_slots_for_designer(cursor, designer_row["id"])

        # 自动补全未来14天的 slots（每次启动都检查）
        today = datetime.now()
        designers_all = conn.execute("SELECT id FROM designers WHERE status = 'active'").fetchall()
        times = get_slots_for_business_hours()
        for day_offset in range(14):
            date = (today + timedelta(days=day_offset)).strftime("%Y-%m-%d")
            for designer in designers_all:
                for t in times:
                    existing = conn.execute(
                        "SELECT id FROM slots WHERE designer_id = ? AND date = ? AND time = ?",
                        (designer["id"], date, t)
                    ).fetchone()
                    if not existing:
                        conn.execute(
                            "INSERT INTO slots (designer_id, date, time) VALUES (?, ?, ?)",
                            (designer["id"], date, t)
                        )

        conn.commit()


class BookingCreate(BaseModel):
    designer_id: Optional[int] = None
    date: str
    time: str
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    service: Optional[str] = None
    store: Optional[str] = None


class BookingReschedule(BaseModel):
    booking_id: int
    new_date: str
    new_time: str


class AdminDesignerCreate(BaseModel):
    name: str
    specialty: Optional[str] = None
    is_available: int = 1


class AdminDesignerUpdate(BaseModel):
    name: str
    specialty: Optional[str] = None
    is_available: int = 1


class AdminServiceCreate(BaseModel):
    name: str
    price: float
    duration_minutes: int
    is_active: int = 1


class AdminServiceUpdate(BaseModel):
    name: str
    price: float
    duration_minutes: int
    is_active: int = 1


class AdminBusinessHoursUpdate(BaseModel):
    store_name: str
    open_time: str
    close_time: str
    break_start: Optional[str] = None
    break_end: Optional[str] = None
    weekly_off: list[int]
    holidays: list[str]


class AdminBookingCancel(BaseModel):
    reason: Optional[str] = None


@app.get("/slots/available")
def get_available_slots(date: str, designer_id: Optional[int] = None):
    with get_db() as conn:
        if designer_id:
            slots = conn.execute(
                """
                SELECT s.id, s.date, s.time, d.name AS designer_name
                FROM slots s
                JOIN designers d ON s.designer_id = d.id
                WHERE s.designer_id = ? AND s.date = ? AND s.is_booked = 0
                  AND d.status = 'active' AND d.is_available = 1
                ORDER BY s.time
                """,
                (designer_id, date),
            ).fetchall()
        else:
            slots = conn.execute(
                """
                SELECT s.id, s.date, s.time, d.name AS designer_name
                FROM slots s
                JOIN designers d ON s.designer_id = d.id
                WHERE s.date = ? AND s.is_booked = 0
                  AND d.status = 'active' AND d.is_available = 1
                ORDER BY s.time, d.name
                """,
                (date,),
            ).fetchall()

    return {
        "status": "available_slots",
        "action": "query_availability",
        "date": date,
        "slots": [dict(slot) for slot in slots],
    }


@app.post("/booking/create")
def create_booking(booking: BookingCreate):
    if booking.designer_id is None:
        with get_db() as conn:
            designer = conn.execute(
                """
                SELECT id FROM designers
                WHERE status = 'active' AND is_available = 1
                ORDER BY RANDOM() LIMIT 1
                """
            ).fetchone()
        if not designer:
            return {"status": "error", "message": "暂无可用的设计师，请稍后再试"}
        booking.designer_id = designer["id"]

    with get_db() as conn:
        cursor = conn.cursor()
        slot = cursor.execute(
            """
            SELECT id, is_booked FROM slots
            WHERE designer_id = ? AND date = ? AND time = ?
            """,
            (booking.designer_id, booking.date, booking.time),
        ).fetchone()

        if not slot:
            return {"status": "error", "message": "该时段不存在，请换个时间试试"}

        if slot["is_booked"] == 1:
            alternatives = get_alternative_slots(
                booking.date,
                store_name=booking.store,
                exclude_time=booking.time,
            )
            return {
                "status": "conflict",
                "message": "该时段已被预约，请选择其他时间或设计师",
                "date": booking.date,
                "time": booking.time,
                "store": booking.store,
                "service": booking.service,
                "customer_name": booking.customer_name,
                "customer_phone": booking.customer_phone,
                "slots": alternatives,
            }

        cursor.execute("UPDATE slots SET is_booked = 1 WHERE id = ?", (slot["id"],))
        cursor.execute(
            """
            INSERT INTO bookings (
                designer_id, slot_id, customer_name, customer_phone,
                service, store, date, time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                booking.designer_id,
                slot["id"],
                booking.customer_name,
                booking.customer_phone,
                booking.service,
                booking.store,
                booking.date,
                booking.time,
            ),
        )
        booking_id = cursor.lastrowid
        designer = cursor.execute(
            "SELECT name FROM designers WHERE id = ?",
            (booking.designer_id,),
        ).fetchone()
        conn.commit()

    return {
        "status": "success",
        "action": "create",
        "booking_id": booking_id,
        "designer_name": designer["name"],
        "customer_name": booking.customer_name,
        "customer_phone": booking.customer_phone,
        "date": booking.date,
        "time": booking.time,
        "service": booking.service,
        "store": booking.store,
        "message": (
            f"预约成功，{booking.date} {booking.time}，设计师 {designer['name']}，"
            f"服务项目：{booking.service or '未指定'}"
        ),
    }


@app.put("/booking/reschedule")
def reschedule_booking(req: BookingReschedule):
    with get_db() as conn:
        cursor = conn.cursor()
        booking = cursor.execute(
            "SELECT * FROM bookings WHERE id = ? AND status = 'active'",
            (req.booking_id,),
        ).fetchone()
        if not booking:
            raise HTTPException(status_code=404, detail="预约记录不存在")

        new_slot = cursor.execute(
            """
            SELECT id, is_booked FROM slots
            WHERE designer_id = ? AND date = ? AND time = ?
            """,
            (booking["designer_id"], req.new_date, req.new_time),
        ).fetchone()
        if not new_slot:
            raise HTTPException(status_code=404, detail="新时段不存在")

        if new_slot["is_booked"] == 1:
            alternatives = get_alternative_slots(
                req.new_date,
                store_name=booking["store"],
                exclude_time=req.new_time,
            )
            return {
                "status": "conflict",
                "message": "新时段已被占用，请选择其他时间",
                "date": req.new_date,
                "time": req.new_time,
                "store": booking["store"],
                "service": booking["service"],
                "customer_name": booking["customer_name"],
                "customer_phone": booking["customer_phone"],
                "slots": alternatives,
            }

        cursor.execute("UPDATE slots SET is_booked = 0 WHERE id = ?", (booking["slot_id"],))
        cursor.execute("UPDATE slots SET is_booked = 1 WHERE id = ?", (new_slot["id"],))
        cursor.execute(
            "UPDATE bookings SET slot_id = ?, date = ?, time = ? WHERE id = ?",
            (new_slot["id"], req.new_date, req.new_time, req.booking_id),
        )
        conn.commit()

    return {
        "status": "success",
        "action": "reschedule",
        "booking_id": req.booking_id,
        "new_date": req.new_date,
        "new_time": req.new_time,
        "message": f"改期成功，已改为 {req.new_date} {req.new_time}",
    }


@app.delete("/booking/cancel")
def cancel_booking(booking_id: int):
    with get_db() as conn:
        cursor = conn.cursor()
        booking = cursor.execute(
            "SELECT * FROM bookings WHERE id = ? AND status = 'active'",
            (booking_id,),
        ).fetchone()
        if not booking:
            return {"status": "not_found", "message": "未找到该预约记录"}

        cursor.execute("UPDATE slots SET is_booked = 0 WHERE id = ?", (booking["slot_id"],))
        cursor.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking_id,))
        conn.commit()
    return {
        "status": "success",
        "action": "cancel",
        "booking_id": booking_id,
        "message": "预约已取消",
    }


def cancel_by_phone_and_date(phone: str, date: str):
    with get_db() as conn:
        cursor = conn.cursor()
        bookings = cursor.execute(
            """
            SELECT * FROM bookings
            WHERE customer_phone = ? AND date = ? AND status = 'active'
            """,
            (phone, date),
        ).fetchall()

        if not bookings:
            return {"status": "not_found", "message": "未找到该手机号在该日期的预约记录"}

        if len(bookings) > 1:
            booking_list = [
                {"booking_id": b["id"], "time": b["time"], "service": b["service"]}
                for b in bookings
            ]
            return {
                "status": "multiple_found",
                "message": f"找到 {len(bookings)} 条预约记录，请确认要取消哪一条",
                "bookings": booking_list,
            }

        booking = bookings[0]
        cursor.execute("UPDATE slots SET is_booked = 0 WHERE id = ?", (booking["slot_id"],))
        cursor.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking["id"],))
        conn.commit()
    return {
        "status": "success",
        "action": "cancel",
        "booking_id": booking["id"],
        "message": f"已取消 {booking['date']} {booking['time']} 的预约",
    }


def cancel_by_reference(reference: str):
    with get_db() as conn:
        cursor = conn.cursor()
        bookings = cursor.execute(
            """
            SELECT * FROM bookings
            WHERE customer_phone LIKE ? AND status = 'active'
            """,
            (f"%{reference}",),
        ).fetchall()

        if not bookings:
            return {"status": "not_found", "message": "未找到匹配的预约记录，请核对手机号后四位"}

        if len(bookings) > 1:
            booking_list = [
                {
                    "booking_id": b["id"],
                    "date": b["date"],
                    "time": b["time"],
                    "service": b["service"],
                }
                for b in bookings
            ]
            return {
                "status": "multiple_found",
                "message": f"找到 {len(bookings)} 条预约记录，请确认要取消哪一条",
                "bookings": booking_list,
            }

        booking = bookings[0]
        cursor.execute("UPDATE slots SET is_booked = 0 WHERE id = ?", (booking["slot_id"],))
        cursor.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking["id"],))
        conn.commit()
    return {
        "status": "success",
        "action": "cancel",
        "booking_id": booking["id"],
        "message": f"已取消 {booking['date']} {booking['time']} 的预约",
    }


def cancel_by_phone(phone: str):
    with get_db() as conn:
        cursor = conn.cursor()
        bookings = cursor.execute(
            """
            SELECT * FROM bookings
            WHERE customer_phone = ? AND status = 'active'
            """,
            (phone,),
        ).fetchall()

        if not bookings:
            return {"status": "not_found", "message": "未找到该手机号的预约记录"}

        if len(bookings) > 1:
            booking_list = [
                {
                    "booking_id": b["id"],
                    "date": b["date"],
                    "time": b["time"],
                    "service": b["service"],
                }
                for b in bookings
            ]
            return {
                "status": "multiple_found",
                "message": f"找到 {len(bookings)} 条预约记录，请确认要取消哪一条",
                "bookings": booking_list,
            }

        booking = bookings[0]
        cursor.execute("UPDATE slots SET is_booked = 0 WHERE id = ?", (booking["slot_id"],))
        cursor.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking["id"],))
        conn.commit()
    return {
        "status": "success",
        "action": "cancel",
        "booking_id": booking["id"],
        "message": f"已取消 {booking['date']} {booking['time']} 的预约",
    }


@app.get("/designers")
def get_designers():
    with get_db() as conn:
        designers = conn.execute(
            """
            SELECT id, name, specialty
            FROM designers
            WHERE status = 'active' AND is_available = 1
            ORDER BY id ASC
            """
        ).fetchall()
    return {"designers": [dict(designer) for designer in designers]}


@app.get("/designers/overview")
def get_designers_overview():
    with get_db() as conn:
        designers = conn.execute(
            """
            SELECT id, name, specialty, status, is_available
            FROM designers
            WHERE status = 'active'
            ORDER BY is_available DESC, id ASC
            """
        ).fetchall()

    items = []
    for designer in designers:
        item = dict(designer)
        item["availability_label"] = "可预约" if item["is_available"] else "暂不可约"
        items.append(item)

    return {"items": items}



def query_booking(phone: Optional[str] = None, booking_reference: Optional[str] = None):
    with get_db() as conn:
        booking = None

        if booking_reference:
            ref_str = str(booking_reference).strip()
            if ref_str.isdigit() and len(ref_str) == 4:
                booking = conn.execute(
                    """
                    SELECT b.*, d.name AS designer_name
                    FROM bookings b
                    LEFT JOIN designers d ON b.designer_id = d.id
                    WHERE b.customer_phone LIKE ? AND b.status = 'active'
                    ORDER BY b.id DESC
                    LIMIT 1
                    """,
                    (f"%{ref_str}",),
                ).fetchone()

            if not booking and ref_str.isdigit():
                booking = conn.execute(
                    """
                    SELECT b.*, d.name AS designer_name
                    FROM bookings b
                    LEFT JOIN designers d ON b.designer_id = d.id
                    WHERE b.id = ? AND b.status = 'active'
                    ORDER BY b.id DESC
                    LIMIT 1
                    """,
                    (int(ref_str),),
                ).fetchone()
            else:
                booking = conn.execute(
                    """
                    SELECT b.*, d.name AS designer_name
                    FROM bookings b
                    LEFT JOIN designers d ON b.designer_id = d.id
                    WHERE b.customer_phone LIKE ? AND b.status = 'active'
                    ORDER BY b.id DESC
                    LIMIT 1
                    """,
                    (f"%{ref_str}",),
                ).fetchone()

        if not booking and phone:
            booking = conn.execute(
                """
                SELECT b.*, d.name AS designer_name
                FROM bookings b
                LEFT JOIN designers d ON b.designer_id = d.id
                WHERE b.customer_phone = ? AND b.status = 'active'
                ORDER BY b.id DESC
                LIMIT 1
                """,
                (phone,),
            ).fetchone()

    if not booking:
        return {
            "status": "not_found",
            "action": "query_booking",
            "message": "未找到匹配的预约记录，请核对手机号或预约单号。"
        }

    return {
        "status": "success",
        "action": "query_booking",
        "booking": {
            "booking_id": booking["id"],
            "customer_name": booking["customer_name"],
            "customer_phone": booking["customer_phone"],
            "service": booking["service"],
            "store": booking["store"],
            "date": booking["date"],
            "time": booking["time"],
            "designer_id": booking["designer_id"],
            "designer_name": booking["designer_name"],
            "status": booking["status"],
        }
    }


@app.post("/dispatch")
def dispatch(req: dict):
    action = req.get("action")
    date = req.get("date")
    time_str = req.get("time")
    phone = req.get("phone")
    store = req.get("store")
    service = req.get("service")
    booking_reference = req.get("booking_reference")

    if action in ("create", "reschedule", "precheck_booking") and date:
        config = get_business_config(store)
        if is_holiday(date, store) or is_rest_day(date, store):
            day_name = "节假日" if is_holiday(date, store) else "休息日"
            return {
                "status": "holiday",
                "message": f"{date} 是{day_name}，门店不营业哦，建议您换个日期预约~",
                "business_hours": {
                    "start": config["open_time"],
                    "end": config["close_time"],
                },
            }
        if time_str and not is_within_business_hours(time_str, store):
            return {
                "status": "closed",
                "message": (
                    f"门店营业时间为 {config['open_time']}-{config['close_time']}，"
                    f"午休 {config['break_start']}-{config['break_end']}，"
                    f"您预约的 {time_str} 不在营业时间内，请换个时间哦"
                ),
                "business_hours": {
                    "start": config["open_time"],
                    "end": config["close_time"],
                },
                "lunch_break": {
                    "start": config["break_start"],
                    "end": config["break_end"],
                },
            }

        if action == "precheck_booking":
            return {
                "status": "ok",
                "action": "precheck_booking",
                "message": "该日期和时间可以继续预约。",
            }

    designer_name = req.get("designer")
    designer_id = req.get("designer_id")
    if designer_name and not designer_id:
        with get_db() as conn:
            designer = conn.execute(
                """
                SELECT id FROM designers
                WHERE name = ? AND status = 'active' AND is_available = 1
                """,
                (designer_name,),
            ).fetchone()
        if designer:
            designer_id = designer["id"]
        else:
            return {
                "status": "error",
                "message": f"未找到设计师：{designer_name}，请重新确认设计师姓名",
            }

    if action in ("query", "query_availability"):
        return get_available_slots(date=date, designer_id=designer_id)

    if action == "query_booking":
        return query_booking(phone=phone, booking_reference=booking_reference)

    if action == "create":
        booking = BookingCreate(
            designer_id=designer_id,
            date=date,
            time=time_str,
            customer_name=req.get("customer_name"),
            customer_phone=phone,
            service=service,
            store=store,
        )
        return create_booking(booking)

    if action == "reschedule":
        booking_id = req.get("booking_id")
        booking_reference = req.get("booking_reference")

        # 兼容前端传来的 booking_reference：
        # 1. 如果是纯数字，优先按 bookings.id 处理
        # 2. 如果不是纯数字，再尝试按手机号后四位匹配
        if not booking_id and booking_reference:
            ref_str = str(booking_reference).strip()

            if ref_str.isdigit():
                booking_id = int(ref_str)
            else:
                with get_db() as conn:
                    booking = conn.execute(
                        "SELECT id FROM bookings WHERE customer_phone LIKE ? AND status = 'active' ORDER BY id DESC",
                        (f"%{ref_str}",),
                    ).fetchone()
                if booking:
                    booking_id = booking["id"]

        # 兜底：如果有手机号和日期，也可以用来找单
        if not booking_id and phone and date:
            with get_db() as conn:
                booking = conn.execute(
                    "SELECT id FROM bookings WHERE customer_phone = ? AND date = ? AND status = 'active'",
                    (phone, date),
                ).fetchone()
            if booking:
                booking_id = booking["id"]
            else:
                return {"status": "not_found", "message": "未找到该预约记录"}

        if not booking_id:
            return {
                "status": "error",
                "message": "改期需要预约单号或手机号，请先确认是哪一单",
            }

        req_obj = BookingReschedule(
            booking_id=booking_id,
            new_date=req.get("new_date", date),
            new_time=req.get("new_time", time_str),
        )
        return reschedule_booking(req_obj)

    if action == "cancel":
        if booking_reference:
            return cancel_by_reference(booking_reference)
        if phone and date:
            return cancel_by_phone_and_date(phone, date)
        if phone:
            return cancel_by_phone(phone)
        if req.get("booking_id"):
            return cancel_booking(req.get("booking_id"))
        return {
            "status": "error",
            "message": "取消预约需要提供手机号后四位，或者手机号+预约日期",
        }

    return {"status": "error", "message": "未知操作"}


# ==================== Admin APIs ====================
@app.get("/admin/designers")
def admin_get_designers(_user: str = Depends(require_admin)):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, name, specialty, status, is_available
            FROM designers
            ORDER BY id DESC
            """
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.post("/admin/designers")
def admin_create_designer(payload: AdminDesignerCreate, _user: str = Depends(require_admin)):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO designers (name, specialty, status, is_available)
            VALUES (?, ?, 'active', ?)
            """,
            (payload.name, payload.specialty, payload.is_available),
        )
        designer_id = cursor.lastrowid
        generate_slots_for_designer(cursor, designer_id)
        conn.commit()
        row = cursor.execute(
            """
            SELECT id, name, specialty, status, is_available
            FROM designers WHERE id = ?
            """,
            (designer_id,),
        ).fetchone()
    return {"item": dict(row)}


@app.put("/admin/designers/{designer_id}")
def admin_update_designer(designer_id: int, payload: AdminDesignerUpdate, _user: str = Depends(require_admin)):
    with get_db() as conn:
        cursor = conn.cursor()
        existing = cursor.execute(
            "SELECT id FROM designers WHERE id = ?",
            (designer_id,),
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="设计师不存在")

        cursor.execute(
            """
            UPDATE designers
            SET name = ?, specialty = ?, is_available = ?, status = ?
            WHERE id = ?
            """,
            (
                payload.name,
                payload.specialty,
                payload.is_available,
                "active" if payload.is_available else "inactive",
                designer_id,
            ),
        )
        conn.commit()
        row = cursor.execute(
            """
            SELECT id, name, specialty, status, is_available
            FROM designers WHERE id = ?
            """,
            (designer_id,),
        ).fetchone()
    return {"item": dict(row)}


@app.delete("/admin/designers/{designer_id}")
def admin_delete_designer(designer_id: int, _user: str = Depends(require_admin)):
    with get_db() as conn:
        cursor = conn.cursor()
        existing = cursor.execute(
            "SELECT id FROM designers WHERE id = ?",
            (designer_id,),
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="设计师不存在")

        cursor.execute(
            """
            UPDATE designers
            SET status = 'inactive', is_available = 0
            WHERE id = ?
            """,
            (designer_id,),
        )
        conn.commit()
    return {"success": True}


@app.get("/admin/services")
def admin_get_services(_user: str = Depends(require_admin)):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, name, price, duration_minutes, is_active
            FROM services
            ORDER BY id DESC
            """
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.post("/admin/services")
def admin_create_service(payload: AdminServiceCreate, _user: str = Depends(require_admin)):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO services (name, price, duration_minutes, is_active)
            VALUES (?, ?, ?, ?)
            """,
            (payload.name, payload.price, payload.duration_minutes, payload.is_active),
        )
        service_id = cursor.lastrowid
        conn.commit()
        row = cursor.execute(
            """
            SELECT id, name, price, duration_minutes, is_active
            FROM services WHERE id = ?
            """,
            (service_id,),
        ).fetchone()
    return {"item": dict(row)}


@app.put("/admin/services/{service_id}")
def admin_update_service(service_id: int, payload: AdminServiceUpdate, _user: str = Depends(require_admin)):
    with get_db() as conn:
        cursor = conn.cursor()
        existing = cursor.execute("SELECT id FROM services WHERE id = ?", (service_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="服务项目不存在")

        cursor.execute(
            """
            UPDATE services
            SET name = ?, price = ?, duration_minutes = ?, is_active = ?
            WHERE id = ?
            """,
            (
                payload.name,
                payload.price,
                payload.duration_minutes,
                payload.is_active,
                service_id,
            ),
        )
        conn.commit()
        row = cursor.execute(
            """
            SELECT id, name, price, duration_minutes, is_active
            FROM services WHERE id = ?
            """,
            (service_id,),
        ).fetchone()
    return {"item": dict(row)}


@app.delete("/admin/services/{service_id}")
def admin_delete_service(service_id: int, _user: str = Depends(require_admin)):
    with get_db() as conn:
        cursor = conn.cursor()
        existing = cursor.execute("SELECT id FROM services WHERE id = ?", (service_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="服务项目不存在")
        cursor.execute("UPDATE services SET is_active = 0 WHERE id = ?", (service_id,))
        conn.commit()
    return {"success": True}


@app.get("/admin/business_hours")
def admin_get_business_hours(_user: str = Depends(require_admin)):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, store_name, open_time, close_time, break_start, break_end,
                   weekly_off, holidays, is_active
            FROM business_hours
            ORDER BY id ASC
            """
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["weekly_off"] = parse_json_array(item["weekly_off"], [])
        item["holidays"] = parse_json_array(item["holidays"], [])
        items.append(item)
    return {"items": items}


@app.put("/admin/business_hours/{record_id}")
def admin_update_business_hours(record_id: int, payload: AdminBusinessHoursUpdate, _user: str = Depends(require_admin)):
    with get_db() as conn:
        cursor = conn.cursor()
        existing = cursor.execute(
            "SELECT id FROM business_hours WHERE id = ?",
            (record_id,),
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="营业时间记录不存在")

        cursor.execute(
            """
            UPDATE business_hours
            SET store_name = ?, open_time = ?, close_time = ?, break_start = ?, break_end = ?,
                weekly_off = ?, holidays = ?
            WHERE id = ?
            """,
            (
                payload.store_name,
                payload.open_time,
                payload.close_time,
                payload.break_start,
                payload.break_end,
                json.dumps(payload.weekly_off, ensure_ascii=False),
                json.dumps(payload.holidays, ensure_ascii=False),
                record_id,
            ),
        )
        conn.commit()
        row = cursor.execute(
            """
            SELECT id, store_name, open_time, close_time, break_start, break_end,
                   weekly_off, holidays, is_active
            FROM business_hours WHERE id = ?
            """,
            (record_id,),
        ).fetchone()
    item = dict(row)
    item["weekly_off"] = parse_json_array(item["weekly_off"], [])
    item["holidays"] = parse_json_array(item["holidays"], [])
    return {"item": item}


@app.get("/admin/bookings")
def admin_get_bookings(
    date: Optional[str] = Query(default=None),
    designer: Optional[str] = Query(default=None),
    _user: str = Depends(require_admin),
):
    with get_db() as conn:
        conditions = ["1=1"]
        params: list[Any] = []

        if date:
            conditions.append("b.date = ?")
            params.append(date)
        if designer:
            conditions.append("d.name LIKE ?")
            params.append(f"%{designer}%")

        rows = conn.execute(
            f"""
            SELECT
                b.id, b.customer_name, b.customer_phone, b.service, b.store,
                b.date, b.time, b.status, b.created_at,
                d.name AS designer_name
            FROM bookings b
            JOIN designers d ON b.designer_id = d.id
            WHERE {' AND '.join(conditions)}
            ORDER BY b.date DESC, b.time DESC, b.id DESC
            """,
            params,
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.post("/admin/bookings/{booking_id}/cancel")
def admin_cancel_booking(booking_id: int, payload: Optional[AdminBookingCancel] = None, _user: str = Depends(require_admin)):
    _ = payload
    result = cancel_booking(booking_id)
    if result["status"] == "not_found":
        raise HTTPException(status_code=404, detail=result["message"])
    return result


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def landing_page():
    index_file = BASE_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(index_file)


@app.get("/admin", include_in_schema=False)
def admin_page():
    admin_file = STATIC_DIR / "admin.html"
    if not admin_file.exists():
        raise HTTPException(status_code=404, detail="admin.html not found")
    return FileResponse(admin_file)


@app.get("/experience", include_in_schema=False)
def experience_page():
    experience_file = STATIC_DIR / "experience.html"
    if not experience_file.exists():
        raise HTTPException(status_code=404, detail="experience.html not found")
    return FileResponse(experience_file)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8003)
