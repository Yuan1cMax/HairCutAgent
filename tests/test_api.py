"""
测试 API 端点：公共接口 + Admin 接口
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest


# ── 辅助函数 ────────────────────────────────────────────
def _weekday_date(offset_days: int = 3) -> str:
    """返回 offset_days 后的日期；避开周一（weekly_off=[0]）"""
    d = datetime.now() + timedelta(days=offset_days)
    while d.weekday() == 0:  # 0=周一，跳过
        d += timedelta(days=1)
    return d.strftime("%Y-%m-%d")


class TestPublicEndpoints:
    """公开接口：无需鉴权"""

    def test_get_designers(self, client):
        resp = client.get("/designers")
        assert resp.status_code == 200
        data = resp.json()
        assert "designers" in data
        assert len(data["designers"]) >= 1
        assert data["designers"][0]["name"] == "测试发型师小王"

    def test_get_available_slots(self, client):
        date = _weekday_date(5)
        resp = client.get(f"/slots/available?date={date}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "available_slots"
        assert "slots" in data

    def test_create_booking_success(self, client):
        """完整预约流程 — 使用未来 14 天内的日期"""
        date = _weekday_date(3)
        resp = client.post("/booking/create", json={
            "designer_id": 1,
            "date": date,
            "time": "10:00",
            "customer_name": "测试用户",
            "customer_phone": "13800000001",
            "service": "洗剪吹",
            "store": "西湖店",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success", f"Failed: {data}"
        assert data["booking_id"] > 0
        assert "预约成功" in data["message"]

    def test_create_booking_slot_not_exist(self, client):
        """预约不存在的时段"""
        date = _weekday_date(4)
        resp = client.post("/booking/create", json={
            "designer_id": 1,
            "date": date,
            "time": "03:00",  # 不在营业时间
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"

    def test_duplicate_booking_conflict(self, client):
        """同一时段重复预约应冲突"""
        date = _weekday_date(5)
        payload = {
            "designer_id": 1,
            "date": date,
            "time": "14:00",
            "customer_name": "用户A",
            "customer_phone": "13800000001",
        }
        r1 = client.post("/booking/create", json=payload)
        assert r1.json()["status"] == "success"

        # 第二次预约同一时段
        r2 = client.post("/booking/create", json=payload)
        assert r2.json()["status"] == "conflict"
        assert "已被预约" in r2.json()["message"]

    def test_query_booking_by_phone(self, client):
        """通过手机号查询预约"""
        date = _weekday_date(6)
        r1 = client.post("/booking/create", json={
            "designer_id": 1,
            "date": date,
            "time": "11:00",
            "customer_name": "查询测试",
            "customer_phone": "13899990001",
        })
        assert r1.json()["status"] == "success"

        resp = client.post("/dispatch", json={
            "action": "query_booking",
            "phone": "13899990001",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["booking"]["customer_name"] == "查询测试"

    def test_cancel_booking(self, client):
        """取消预约"""
        date = _weekday_date(7)
        r1 = client.post("/booking/create", json={
            "designer_id": 1,
            "date": date,
            "time": "15:00",
            "customer_name": "取消测试",
            "customer_phone": "13800000002",
        })
        assert r1.json()["status"] == "success"
        booking_id = r1.json()["booking_id"]

        r2 = client.delete(f"/booking/cancel?booking_id={booking_id}")
        assert r2.status_code == 200
        assert r2.json()["status"] == "success"
        assert "已取消" in r2.json()["message"]

    def test_reschedule_booking(self, client):
        """改期"""
        date1 = _weekday_date(8)
        date2 = _weekday_date(9)
        r1 = client.post("/booking/create", json={
            "designer_id": 1,
            "date": date1,
            "time": "09:30",
            "customer_name": "改期测试",
            "customer_phone": "13800000003",
        })
        assert r1.json()["status"] == "success"
        booking_id = r1.json()["booking_id"]

        r2 = client.put("/booking/reschedule", json={
            "booking_id": booking_id,
            "new_date": date2,
            "new_time": "13:30",
        })
        assert r2.status_code == 200
        assert r2.json()["status"] == "success"
        assert "改期成功" in r2.json()["message"]

    def test_dispatch_holiday_reject(self, client):
        """节假日不接单"""
        resp = client.post("/dispatch", json={
            "action": "create",
            "date": "2026-01-01",
            "time": "10:00",
            "customer_name": "元旦用户",
            "customer_phone": "13800000004",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "holiday"

    def test_dispatch_closed_reject(self, client):
        """非营业时间不接单 — 使用工作日但时间在营业外"""
        date = _weekday_date(10)
        resp = client.post("/dispatch", json={
            "action": "create",
            "date": date,
            "time": "06:00",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "closed", f"Expected closed, got {data}"


class TestAdminAuth:
    """Admin 鉴权测试"""

    def test_admin_endpoint_without_token_returns_401(self, client):
        resp = client.get("/admin/designers")
        assert resp.status_code == 401

    def test_admin_endpoint_without_config_returns_503(self, test_db, monkeypatch):
        import database
        import main

        monkeypatch.setattr(database, "DB_PATH", test_db)
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        main.app.dependency_overrides.clear()

        from fastapi.testclient import TestClient

        with TestClient(main.app) as local_client:
            resp = local_client.get(
                "/admin/designers",
                headers={"Authorization": "Bearer any-token"},
            )

        assert resp.status_code == 503
        assert resp.json()["detail"] == "Admin 鉴权未配置，当前环境已禁用管理接口"

    def test_admin_endpoint_with_wrong_token_returns_403(self, client):
        resp = client.get(
            "/admin/designers",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 403

    def test_admin_endpoint_with_valid_token(self, client, admin_headers):
        resp = client.get("/admin/designers", headers=admin_headers)
        assert resp.status_code == 200
        assert "items" in resp.json()


class TestAdminCRUD:
    """Admin CRUD 操作"""

    def test_create_and_delete_designer(self, client, admin_headers):
        resp = client.post("/admin/designers", json={
            "name": "新设计师", "specialty": "染发",
        }, headers=admin_headers)
        assert resp.status_code == 200
        new_id = resp.json()["item"]["id"]

        # 删除（软删除）
        resp = client.delete(f"/admin/designers/{new_id}", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_create_and_update_service(self, client, admin_headers):
        resp = client.post("/admin/services", json={
            "name": "测试服务", "price": 99.0, "duration_minutes": 30,
        }, headers=admin_headers)
        assert resp.status_code == 200
        svc_id = resp.json()["item"]["id"]

        resp = client.put(f"/admin/services/{svc_id}", json={
            "name": "测试服务-改名", "price": 129.0, "duration_minutes": 45, "is_active": 1,
        }, headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["item"]["price"] == 129.0

    def test_get_business_hours(self, client, admin_headers):
        resp = client.get("/admin/business_hours", headers=admin_headers)
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) >= 1
        assert items[0]["store_name"] == "西湖店"

    def test_get_bookings(self, client, admin_headers):
        resp = client.get("/admin/bookings", headers=admin_headers)
        assert resp.status_code == 200
        assert "items" in resp.json()

    def test_get_services(self, client, admin_headers):
        resp = client.get("/admin/services", headers=admin_headers)
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) >= 2  # 种子数据有2条
