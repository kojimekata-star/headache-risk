import os
import time
import requests
import streamlit as st
from urllib.parse import urlencode
from lib.database import get_conn

SCOPES = [
    "https://www.googleapis.com/auth/googlehealth.sleep.readonly",
    "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",
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
            VALUES (1, ?, ?, ?, ?)
        """, (
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
    return resp.json()

def _fitness_get(path: str, params: dict = None) -> dict | None:
    return _health_get(path, params)

def sync_sleep(date_str: str) -> bool:
    from datetime import datetime, timedelta
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    next_dt = dt + timedelta(days=1)
    # startTimeのUTC範囲でフィルタ（就寝日基準）
    # JST date_str の夜 = UTC 前日15:00〜当日14:59
    utc_start = (dt - timedelta(hours=9)).strftime("%Y-%m-%dT15:00:00Z")
    utc_end = (dt - timedelta(hours=9) + timedelta(days=1)).strftime("%Y-%m-%dT14:59:59Z")
    
    data = _health_get(
        "/users/me/dataTypes/sleep/dataPoints",
        params={"filter": f'sleep.interval.civil_end_time >= "{date_str}" AND sleep.interval.civil_end_time < "{next_dt.strftime("%Y-%m-%d")}"'}
    )
    if not data or not data.get("dataPoints"):
        return False

    point = data["dataPoints"][0]
    sleep = point.get("sleep", {})
    interval = sleep.get("interval", {})
    start_time = interval.get("startTime", "")
    end_time = interval.get("endTime", "")
    
    # UTCオフセットからJST日付を計算
    utc_offset_s = int(interval.get("startUtcOffset", "0s").rstrip("s"))
    actual_date = date_str
    if start_time:
        try:
            s_utc = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            s_local = s_utc + timedelta(seconds=utc_offset_s)
            actual_date = s_local.strftime("%Y-%m-%d")
        except Exception:
            pass

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
        """, (actual_date, start_time, end_time, duration_min, 0,
               deep_min, light_min, rem_min, wake_min))
    return True

def sync_hrv(date_str: str) -> bool:
    data = _health_get(
        "/users/me/dataTypes/daily-resting-heart-rate/dataPoints:dailyRollUp",
        params=None
    )
    resting_hr = None
    if data and data.get("rollupDataPoints"):
        for point in data["rollupDataPoints"]:
            civil = point.get("civilStartTime", {}).get("date", {})
            y = civil.get("year")
            m = civil.get("month")
            d = civil.get("day")
            if y and m and d:
                point_date = f"{y}-{m:02d}-{d:02d}"
                if point_date == date_str:
                    resting_hr = point.get("dailyRestingHeartRate", {}).get("beatsPerMinute")
                    break
    if resting_hr is None:
        return False
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO fitbit_hrv (date, rmssd, resting_hr, coverage)
            VALUES (?,?,?,?)
        """, (date_str, None, resting_hr, None))
    return True

