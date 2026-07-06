import os
import time
import requests
import streamlit as st
from urllib.parse import urlencode
from lib.database import get_conn

SCOPES = [
    "https://www.googleapis.com/auth/googlehealth.sleep.readonly",
    "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",
    "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly",
]

def _creds():
    client_id = st.secrets.get("GOOGLE_CLIENT_ID", os.getenv("GOOGLE_CLIENT_ID", ""))
    client_secret = st.secrets.get("GOOGLE_CLIENT_SECRET", os.getenv("GOOGLE_CLIENT_SECRET", ""))
    return client_id, client_secret

def _redirect_uri():
    return st.secrets.get("GOOGLE_REDIRECT_URI", os.getenv("GOOGLE_REDIRECT_URI", "https://kojimekata-star-headache-risk-home-xwpblk.streamlit.app"))

def get_auth_url() -> str:
    client_id, _ = _creds()
    params = {
        "client_id": client_id,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "redirect_uri": _redirect_uri(),
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"

def exchange_code(code: str) -> dict:
    client_id, client_secret = _creds()
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _redirect_uri(),
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()

def save_tokens(token_data: dict):
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO fitbit_tokens (id, access_token, refresh_token, expires_at, fitbit_user_id)
            VALUES (?, ?, ?, ?, ?)
        """, (
            1,
            token_data["access_token"],
            token_data.get("refresh_token", ""),
            int(time.time()) + token_data.get("expires_in", 3600),
            token_data.get("sub", ""),
        ))

def get_tokens() -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM fitbit_tokens WHERE id=1").fetchone()
    return dict(row) if row else None

def _get_valid_token() -> str | None:
    tokens = get_tokens()
    if not tokens:
        return None
    if time.time() < tokens["expires_at"] - 60:
        return tokens["access_token"]
    client_id, client_secret = _creds()
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=10,
    )
    if resp.status_code == 200:
        new_tokens = resp.json()
        new_tokens.setdefault("refresh_token", tokens["refresh_token"])
        save_tokens(new_tokens)
        return new_tokens["access_token"]
    return None

def _health_get(path: str, params: dict = None) -> dict | None:
    token = _get_valid_token()
    if not token:
        return None
    resp = requests.get(
        f"https://health.googleapis.com/v4{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=10,
    )
    if not resp.ok:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:500]}")
    return resp.json()

def sync_sleep(date_str: str) -> bool:
    from datetime import datetime, timedelta

    data = _health_get(
        "/users/me/dataTypes/sleep/dataPoints",
        params={"pageSize": 30}
    )
    if not data or not data.get("dataPoints"):
        return False

    target_point = None
    for point in data["dataPoints"]:
        sleep = point.get("sleep", {})
        interval = sleep.get("interval", {})
        start_time = interval.get("startTime", "")
        utc_offset_s = int(interval.get("startUtcOffset", "0s").rstrip("s"))
        if start_time:
            try:
                s_utc = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                s_local = s_utc + timedelta(seconds=utc_offset_s)
                if s_local.strftime("%Y-%m-%d") == date_str:
                    target_point = point
                    break
            except Exception:
                pass

    if not target_point:
        return False

    sleep = target_point.get("sleep", {})
    interval = sleep.get("interval", {})
    start_time = interval.get("startTime", "")
    end_time = interval.get("endTime", "")
    duration_min = 0
    if start_time and end_time:
        try:
            s = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            e = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            duration_min = int((e - s).total_seconds() / 60)
        except Exception:
            pass

    stages = sleep.get("stages", [])
    deep_min = light_min = rem_min = wake_min = 0
    for stage in stages:
        stage_type = stage.get("type", "")
        try:
            st_start = datetime.fromisoformat(stage["startTime"].replace("Z", "+00:00"))
            st_end = datetime.fromisoformat(stage["endTime"].replace("Z", "+00:00"))
            mins = int((st_end - st_start).total_seconds() / 60)
        except Exception:
            mins = 0
        if stage_type == "DEEP": deep_min += mins
        elif stage_type == "LIGHT": light_min += mins
        elif stage_type == "REM": rem_min += mins
        elif stage_type == "AWAKE": wake_min += mins

    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO fitbit_sleep
            (date, sleep_start, sleep_end, duration_min, efficiency, deep_min, light_min, rem_min, wake_min)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (date_str, start_time, end_time, duration_min, 0,
               deep_min, light_min, rem_min, wake_min))
    return True

def sync_hrv(date_str: str) -> bool:
    data = _health_get(
        "/users/me/dataTypes/daily-resting-heart-rate/dataPoints",
        params={"pageSize": 30}
    )

    resting_hr = None
    if data and data.get("dataPoints"):
        for point in data["dataPoints"]:
            rhr = point.get("dailyRestingHeartRate", {})
            date_obj = rhr.get("date", {})
            point_date = f"{date_obj.get('year', '')}-{str(date_obj.get('month', '')).zfill(2)}-{str(date_obj.get('day', '')).zfill(2)}"
            if point_date == date_str:
                resting_hr = int(rhr.get("beatsPerMinute", 0))
                break

    if not resting_hr:
        return False

    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO fitbit_hrv (date, rmssd, resting_hr, coverage)
            VALUES (?,?,?,?)
        """, (date_str, None, resting_hr, None))
    return True
