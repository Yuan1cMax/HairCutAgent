"""
测试核心业务逻辑：时间工具函数、营业规则校验、slot 生成
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

# ── 导入被测试函数 ────────────────────────────────────────
from main import (
    is_holiday,
    is_rest_day,
    is_time_in_range,
    is_within_business_hours,
    parse_json_array,
    time_to_minutes,
    get_slots_for_business_hours,
)


class TestTimeUtils:
    """时间工具函数 — 不依赖数据库"""

    def test_time_to_minutes(self):
        assert time_to_minutes("09:00") == 540
        assert time_to_minutes("00:00") == 0
        assert time_to_minutes("23:59") == 1439
        assert time_to_minutes("12:30") == 750

    def test_is_time_in_range_true(self):
        assert is_time_in_range("09:00", "09:00", "21:00") is True
        assert is_time_in_range("14:30", "09:00", "21:00") is True
        assert is_time_in_range("20:59", "09:00", "21:00") is True

    def test_is_time_in_range_false(self):
        assert is_time_in_range("08:59", "09:00", "21:00") is False
        assert is_time_in_range("21:00", "09:00", "21:00") is False  # 左闭右开
        assert is_time_in_range("23:00", "09:00", "21:00") is False


class TestParseJsonArray:
    """JSON 数组解析 — 不依赖数据库"""

    def test_normal_array(self):
        assert parse_json_array('[1, 2, 3]', []) == [1, 2, 3]

    def test_empty_string(self):
        assert parse_json_array("", [0]) == [0]

    def test_none_value(self):
        assert parse_json_array(None, [0]) == [0]

    def test_invalid_json(self):
        assert parse_json_array("not-json", [0]) == [0]

    def test_non_array_json(self):
        assert parse_json_array('{"a": 1}', [0]) == [0]


class TestBusinessRules:
    """营业规则校验 — 需要注入测试 DB 路径"""

    @pytest.fixture(autouse=True)
    def _setup_db(self, test_db, monkeypatch):
        """注入测试数据库路径（test_db 来自 conftest.py）"""
        import database
        monkeypatch.setattr(database, "DB_PATH", test_db)

    def test_is_holiday_returns_true(self):
        """元旦在种子数据中标记为节假日"""
        assert is_holiday("2026-01-01") is True

    def test_is_holiday_returns_false(self):
        """普通日期不是节假日"""
        assert is_holiday("2026-03-15") is False

    def test_is_rest_day_sunday(self):
        """周日（weekday=6，但 weekly_off=[0] 表示周一休息）"""
        # 种子数据 weekly_off = [0]，0=周一
        # 2026-03-16 是周一，应该是休息日
        assert is_rest_day("2026-03-16") is True  # 周一 = weekday 0

    def test_is_rest_day_weekday(self):
        """周二不是休息日"""
        # 2026-03-17 是周二
        assert is_rest_day("2026-03-17") is False

    def test_is_within_business_hours_valid(self):
        assert is_within_business_hours("10:00") is True
        assert is_within_business_hours("15:00") is True

    def test_is_within_business_hours_lunch_break(self):
        """午休时间不在营业时间内"""
        assert is_within_business_hours("12:30") is False

    def test_is_within_business_hours_before_open(self):
        assert is_within_business_hours("08:00") is False

    def test_is_within_business_hours_after_close(self):
        assert is_within_business_hours("22:00") is False

    def test_is_within_business_hours_edge_open(self):
        """09:00 刚好开门"""
        assert is_within_business_hours("09:00") is True

    def test_is_within_business_hours_edge_close(self):
        """21:00 已关门（左闭右开）"""
        assert is_within_business_hours("21:00") is False


class TestSlotGeneration:
    """slot 时间槽生成 — 需要注入测试 DB 路径"""

    @pytest.fixture(autouse=True)
    def _setup_db(self, test_db, monkeypatch):
        import database
        monkeypatch.setattr(database, "DB_PATH", test_db)

    def test_skips_lunch_break(self):
        slots = get_slots_for_business_hours()
        assert "12:00" not in slots
        assert "12:30" not in slots

    def test_starts_at_open_time(self):
        slots = get_slots_for_business_hours()
        assert slots[0] == "09:00"

    def test_ends_before_close_time(self):
        slots = get_slots_for_business_hours()
        assert all(time_to_minutes(s) < time_to_minutes("21:00") for s in slots)

    def test_all_slots_30min_interval(self):
        slots = get_slots_for_business_hours()
        for i in range(1, len(slots)):
            prev = time_to_minutes(slots[i - 1])
            curr = time_to_minutes(slots[i])
            diff = curr - prev
            assert diff >= 30, f"Slot gap between {slots[i-1]} and {slots[i]} is {diff}min"
