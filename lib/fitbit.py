import os
import time
import requests
import streamlit as st
from urllib.parse import urlencode
from lib.database import get_conn

SCOPES = [
    "https://www.googleapis.com/auth/health.sleep.readonly",
    "https://www.googleapis.com/auth/health.heart_rate.readonly",
    "https://www.googleapis.com/auth/health.activity.readonly",
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

# デバッグ用（3_FitBit.pyから呼び出し）
def _fitness_get(path: str, params: dict = None) -> dict | None:
    return _health_get(path, params)

def sync_sleep(date_str: str) -> bool:
    from datetime import datetime, timezone
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    data = _health_get(
        "/users/-/sleepSessions",
        params={
            "startTime": dt.strftime("%Y-%m-%dT00:00:00Z"),
            "endTime": dt.strftime("%Y-%m-%dT23:59:59Z"),
        }
    )
    if not data or not data.get("session"):
        return False
    session = data["session"][0]
    start_ms = session.get("startTimeMillis", "0")
    end_ms = session.get("endTimeMillis", "0")
    duration_min = (int(end_ms) - int(start_ms)) // 60000
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO fitbit_sleep
            (date, sleep_start, sleep_end, duration_min, efficiency, deep_min, light_min, rem_min, wake_min)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (date_str, start_ms, end_ms, duration_min, 0, 0, 0, 0, 0))
    return True

def sync_hrv(date_str: str) -> bool:
    from datetime import datetime, timezone
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    data = _health_get(
        "/users/-/heartRate:dailyAggregation",
        params={"date": date_str}
    )
    resting_hr = None
    if data and data.get("dailyHeartRateMetrics"):
        metrics = data["dailyHeartRateMetrics"]
        resting_hr = metrics.get("restingHeartRate")
    if resting_hr is None:
        return False
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO fitbit_hrv (date, rmssd, resting_hr, coverage)
            VALUES (?,?,?,?)
        """, (date_str, None, resting_hr, None))
    return True
