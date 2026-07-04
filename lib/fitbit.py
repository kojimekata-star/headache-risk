import os
import time
import requests
from urllib.parse import urlencode
from lib.database import get_conn

SCOPES = ["sleep", "heartrate", "activity", "profile"]


def _creds():
    return os.getenv("FITBIT_CLIENT_ID", ""), os.getenv("FITBIT_CLIENT_SECRET", "")


def _redirect_uri():
    return os.getenv("FITBIT_REDIRECT_URI", "https://kojimekata-star-headache-risk-home-xwpblk.streamlit.app")


def get_auth_url() -> str:
    client_id, _ = _creds()
    params = {
        "client_id": client_id,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "redirect_uri": _redirect_uri(),
    }
    return f"https://www.fitbit.com/oauth2/authorize?{urlencode(params)}"


def exchange_code(code: str) -> dict:
    client_id, client_secret = _creds()
    resp = requests.post(
        "https://api.fitbit.com/oauth2/token",
        auth=(client_id, client_secret),
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _redirect_uri(),
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
            token_data["refresh_token"],
            int(time.time()) + token_data.get("expires_in", 28800),
            token_data.get("user_id", ""),
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
    # Refresh
    client_id, client_secret = _creds()
    resp = requests.post(
        "https://api.fitbit.com/oauth2/token",
        auth=(client_id, client_secret),
        data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]},
        timeout=10,
    )
    if resp.status_code == 200:
        save_tokens(resp.json())
        return resp.json()["access_token"]
    return None


def _get(path: str) -> dict | None:
    token = _get_valid_token()
    if not token:
        return None
    resp = requests.get(
        f"https://api.fitbit.com{path}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    return resp.json() if resp.status_code == 200 else None


def sync_sleep(date_str: str) -> bool:
    data = _get(f"/1.2/user/-/sleep/date/{date_str}.json")
    if not data or not data.get("sleep"):
        return False
    sleep = next((s for s in data["sleep"] if s.get("isMainSleep")), data["sleep"][0])
    levels = sleep.get("levels", {}).get("summary", {})
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO fitbit_sleep
            (date, sleep_start, sleep_end, duration_min, efficiency, deep_min, light_min, rem_min, wake_min)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            date_str,
            sleep.get("startTime"),
            sleep.get("endTime"),
            sleep.get("minutesAsleep"),
            sleep.get("efficiency"),
            levels.get("deep", {}).get("minutes", 0),
            levels.get("light", {}).get("minutes", 0),
            levels.get("rem", {}).get("minutes", 0),
            levels.get("wake", {}).get("minutes", 0),
        ))
    return True


def sync_hrv(date_str: str) -> bool:
    hrv_data = _get(f"/1/user/-/hrv/date/{date_str}.json")
    hr_data = _get(f"/1/user/-/activities/heart/date/{date_str}/1d.json")

    rmssd = None
    coverage = None
    resting_hr = None

    if hrv_data and hrv_data.get("hrv"):
        entry = hrv_data["hrv"][0] if hrv_data["hrv"] else None
        if entry:
            rmssd = entry.get("value", {}).get("dailyRmssd")
            coverage = entry.get("value", {}).get("coverage")

    if hr_data:
        try:
            resting_hr = hr_data["activities-heart"][0]["value"]["restingHeartRate"]
        except (KeyError, IndexError, TypeError):
            pass

    if rmssd is None and resting_hr is None:
        return False

    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO fitbit_hrv (date, rmssd, resting_hr, coverage)
            VALUES (?,?,?,?)
        """, (date_str, rmssd, resting_hr, coverage))
    return True
