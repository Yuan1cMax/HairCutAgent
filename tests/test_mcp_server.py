from __future__ import annotations

from datetime import datetime, timedelta


def _date_after(days: int) -> str:
    """返回测试配置中的下一个营业日。"""
    date = datetime.now() + timedelta(days=days)
    holidays = {"2026-01-01", "2026-05-01"}
    while date.weekday() == 0 or date.strftime("%Y-%m-%d") in holidays:
        date += timedelta(days=1)
    return date.strftime("%Y-%m-%d")


def test_list_services_reads_active_services(test_db, monkeypatch):
    import database
    import mcp_server

    monkeypatch.setattr(database, "DB_PATH", test_db)
    result = mcp_server.list_services()

    assert result["status"] == "success"
    assert result["items"]
    assert all("price" in item for item in result["items"])


def test_get_business_hours_reads_store_rules(test_db, monkeypatch):
    import database
    import mcp_server

    monkeypatch.setattr(database, "DB_PATH", test_db)
    result = mcp_server.get_business_hours("西湖店")

    assert result["status"] == "success"
    assert result["store"] == "西湖店"
    assert result["business_hours"]["open_time"] == "09:00"


def test_get_available_slots_returns_real_slots(test_db, monkeypatch):
    import database
    import mcp_server

    monkeypatch.setattr(database, "DB_PATH", test_db)
    result = mcp_server.get_available_slots(_date_after(3), designer_id=1)

    assert result["status"] == "available_slots"
    assert result["slots"]
    assert result["source"] == "haircutagent.sqlite"


def test_get_available_slots_returns_holiday_status(test_db, monkeypatch):
    import database
    import mcp_server

    monkeypatch.setattr(database, "DB_PATH", test_db)
    result = mcp_server.get_available_slots("2026-01-01")

    assert result["status"] == "holiday"
    assert result["slots"] == []


def test_get_available_slots_rejects_invalid_date(test_db, monkeypatch):
    import database
    import mcp_server

    monkeypatch.setattr(database, "DB_PATH", test_db)

    try:
        mcp_server.get_available_slots("2026/01/01")
    except ValueError as exc:
        assert "YYYY-MM-DD" in str(exc)
    else:
        raise AssertionError("invalid dates must be rejected")
