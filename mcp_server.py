"""Read-only MCP adapter for the HairCutAgent business backend."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from mcp.server.fastmcp import FastMCP

import main


mcp = FastMCP(
    "HairCutAgent",
    instructions=(
        "Read-only access to current barber-shop services, business hours, "
        "and available appointment slots. Never claim that a booking was "
        "created because this server exposes no write tools."
    ),
    host=os.getenv("MCP_HOST", "127.0.0.1"),
    port=int(os.getenv("MCP_PORT", "8004")),
    streamable_http_path="/mcp",
)


def _validate_date(date: str) -> None:
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("date must use YYYY-MM-DD format") from exc


@mcp.tool()
def list_services() -> dict[str, Any]:
    """List active barber services and their current price and duration."""
    with main.get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, name, price, duration_minutes
            FROM services
            WHERE is_active = 1
            ORDER BY id
            """
        ).fetchall()

    return {
        "status": "success",
        "items": [dict(row) for row in rows],
        "source": "haircutagent.sqlite",
    }


@mcp.tool()
def get_business_hours(store_name: str | None = None) -> dict[str, Any]:
    """Return the current business hours and closure rules for a store."""
    config = main.get_business_config(store_name)
    return {
        "status": "success",
        "store": config["store_name"],
        "business_hours": config,
        "source": "haircutagent.sqlite",
    }


@mcp.tool()
def get_available_slots(
    date: str,
    store_name: str | None = None,
    designer_id: int | None = None,
) -> dict[str, Any]:
    """Return real available slots, including closure status for the date."""
    _validate_date(date)
    config = main.get_business_config(store_name)
    store = config["store_name"]

    if main.is_holiday(date, store):
        return {
            "status": "holiday",
            "date": date,
            "store": store,
            "slots": [],
            "message": "The store is closed for a holiday.",
        }

    if main.is_rest_day(date, store):
        return {
            "status": "rest_day",
            "date": date,
            "store": store,
            "slots": [],
            "message": "The store is closed on its weekly rest day.",
        }

    result = main.get_available_slots(date=date, designer_id=designer_id)
    result["store"] = store
    result["business_hours"] = {
        "open_time": config["open_time"],
        "close_time": config["close_time"],
        "break_start": config["break_start"],
        "break_end": config["break_end"],
    }
    result["source"] = "haircutagent.sqlite"
    return result


def run() -> None:
    """Start the MCP server in stdio or Streamable HTTP mode."""
    main.startup()
    transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
    if transport not in {"stdio", "sse", "streamable-http"}:
        raise ValueError("MCP_TRANSPORT must be stdio, sse, or streamable-http")
    mcp.run(transport=transport)


if __name__ == "__main__":
    run()
