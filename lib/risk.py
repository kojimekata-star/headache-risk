import math
import pandas as pd
from datetime import datetime, timedelta
from lib.database import get_conn
from lib.pressure import compute_pressure_features


def _sleep_score(date_str: str) -> float:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT date, duration_min, efficiency, deep_min, rem_min
            FROM fitbit_sleep
            WHERE date <= ?
            ORDER BY date DESC LIMIT 30
        """, (date_str,)).fetchall()
    if not rows:
        return 0.5
    df = pd.DataFrame([dict(r) for r in rows])
    today = df.iloc[0]
    baseline = df.iloc[1:] if len(df) > 1 else df
    if baseline.empty or today["duration_min"] is None:
        return 0.5
    mean_dur = baseline["duration_min"].mean()
    std_dur = baseline["duration_min"].std() or 30
    dur_dev = abs(today["duration_min"] - mean_dur) / std_dur
    score = min(dur_dev / 3.0, 1.0)
    return round(score, 3)


def _hrv_score(date_str: str) -> float:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT date, resting_hr FROM fitbit_hrv
            WHERE date <= ? AND resting_hr IS NOT NULL
            ORDER BY date DESC LIMIT 30
        """, (date_str,)).fetchall()
    if not rows:
        return 0.5
    df = pd.DataFrame([dict(r) for r in rows])
    today_hr = df.iloc[0]["resting_hr"]
    baseline = df.iloc[1:] if len(df) > 1 else df
    if baseline.empty or today_hr is None:
        return 0.5
    mean_hr = baseline["resting_hr"].mean()
    std_hr = baseline["resting_hr"].std() or 3
    # 安静時心拍数が平均より高いほどリスク上昇
    z = (float(today_hr) - mean_hr) / std_hr
    score = min(max(z / 3.0, 0.0), 1.0)
    return round(score, 3)


def _pressure_score() -> float:
    features = compute_pressure_features(hours=48)
    if features["max_change"] is None:
        return 0.3
    change_risk = min(features["max_change"] / 10.0, 1.0)
    drop_risk = 0.0
    if features["change_6h"] is not None and features["change_6h"] < -3:
        drop_risk = min(abs(features["change_6h"]) / 8.0, 1.0)
    return round(max(change_risk, drop_risk), 3)


def compute_risk(date_str: str | None = None) -> dict:
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    sleep = _sleep_score(date_str)
    hrv = _hrv_score(date_str)
    pressure = _pressure_score()
    sleep = float(sleep) if sleep is not None else 0.5
    hrv = float(hrv) if hrv is not None else 0.5
    pressure = float(pressure) if pressure is not None else 0.3
    if math.isnan(sleep): sleep = 0.5
    if math.isnan(hrv): hrv = 0.5
    if math.isnan(pressure): pressure = 0.3
    weights = {"sleep": 0.35, "hrv": 0.35, "pressure": 0.30}
    total = sleep * weights["sleep"] + hrv * weights["hrv"] + pressure * weights["pressure"]
    total = min(max(total, 0.0), 1.0)

    def pct(v):
        v = float(v)
        if math.isnan(v): return 0
        return round(min(max(v, 0.0), 1.0) * 100)

    return {
        "date": date_str,
        "total": pct(total),
        "sleep": pct(sleep),
        "hrv": pct(hrv),
        "pressure": pct(pressure),
    }


def compute_risk_history(days: int = 30) -> list[dict]:
    results = []
    today = datetime.now().date()
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        results.append(compute_risk(d.strftime("%Y-%m-%d")))
    return results
