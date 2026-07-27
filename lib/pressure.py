import requests
from datetime import datetime, timedelta
from lib.database import get_conn, get_setting


def get_location() -> tuple[float, float]:
    return float(get_setting("lat", "35.6762")), float(get_setting("lon", "139.6503"))


def sync_pressure(days: int = 14) -> int:
    lat, lon = get_location()
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    resp = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "hourly": "surface_pressure",
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
            "timezone": "Asia/Tokyo",
            "models": "jma_msm",
        },
        timeout=15,
    )
    
    resp.raise_for_status()
    data = resp.json()

    records = [
        {"timestamp": t, "pressure_hpa": p, "lat": lat, "lon": lon}
        for t, p in zip(data["hourly"]["time"], data["hourly"]["surface_pressure"])
        if p is not None
    ]

    with get_conn() as conn:
        conn.executemany("""
            INSERT OR REPLACE INTO pressure_log (timestamp, pressure_hpa, lat, lon)
            VALUES (:timestamp, :pressure_hpa, :lat, :lon)
        """, records)

    return len(records)


def get_recent_pressure(hours: int = 48) -> list[dict]:
    since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M")
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT timestamp, pressure_hpa FROM pressure_log
            WHERE timestamp >= ?
            ORDER BY timestamp ASC
        """, (since,)).fetchall()
    return [dict(r) for r in rows]


def compute_pressure_features(hours: int = 48) -> dict:
    rows = get_recent_pressure(hours)
    if len(rows) < 2:
        return {"current": None, "change_3h": None, "change_6h": None, "max_change": None}

    pressures = [r["pressure_hpa"] for r in rows]
    current = pressures[-1]
    n = len(pressures)

    change_3h = pressures[-1] - pressures[max(0, n - 3)] if n >= 3 else None
    change_6h = pressures[-1] - pressures[max(0, n - 6)] if n >= 6 else None
    max_change = max(pressures) - min(pressures)

    return {
        "current": round(current, 1),
        "change_3h": round(change_3h, 1) if change_3h is not None else None,
        "change_6h": round(change_6h, 1) if change_6h is not None else None,
        "max_change": round(max_change, 1),
    }
