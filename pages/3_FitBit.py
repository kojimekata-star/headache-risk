import streamlit as st
from datetime import datetime, timedelta
from lib.database import init_db
from lib.fitbit import get_tokens, get_auth_url, exchange_code, save_tokens, sync_sleep, sync_hrv
from lib.pressure import sync_pressure

init_db()

st.set_page_config(page_title="FitBit連携", page_icon="⌚", layout="wide")
st.title("⌚ FitBit連携・データ同期")

params = st.query_params
if "code" in params:
    code = params["code"]
    try:
        token_data = exchange_code(code)
        save_tokens(token_data)
        st.query_params.clear()
        st.success("✅ FitBitとの連携が完了しました。")
        st.rerun()
    except Exception as e:
        st.error(f"認証エラー: {e}")

tokens = get_tokens()
client_id = st.secrets.get("GOOGLE_CLIENT_ID", "")

st.subheader("接続状態")
col1, col2 = st.columns(2)
with col1:
    if tokens:
        st.success("✅ FitBit 連携済み")
        import time
        remaining = tokens["expires_at"] - int(time.time())
        if remaining > 0:
            st.caption(f"トークン有効期限: あと {remaining // 3600}h {(remaining % 3600) // 60}m")
        else:
            st.warning("トークンが期限切れです（次回アクセス時に自動更新）")
    else:
        st.error("❌ 未連携")

with col2:
    if not client_id:
        st.warning("GOOGLE_CLIENT_ID が未設定です")
    elif not tokens:
        if st.button("⌚ FitBitと連携する", type="primary"):
            auth_url = get_auth_url()
            st.markdown(f"[クリックして認証ページへ]({auth_url})")

st.divider()

st.subheader("データ同期")

col_sync1, col_sync2 = st.columns(2)

with col_sync1:
    st.markdown("**FitBitデータ（睡眠・HRV）**")
    sync_days = st.slider("同期する日数", 1, 30, 14, key="sync_days")
    if st.button("🔄 FitBitデータを同期", disabled=not tokens):
        if tokens:
            progress = st.progress(0)
            success_sleep = 0
            success_hrv = 0
            today = datetime.now().date()
            for i in range(sync_days):
                d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
                if sync_sleep(d):
                    success_sleep += 1
                if sync_hrv(d):
                    success_hrv += 1
                progress.progress((i + 1) / sync_days)
            progress.empty()
            st.success(f"同期完了: 睡眠 {success_sleep}日分 / HRV {success_hrv}日分")

with col_sync2:
    st.markdown("**気圧データ（Open-Meteo）**")
    pressure_days = st.slider("取得する日数", 1, 30, 14, key="pressure_days")
    if st.button("🌪 気圧データを取得"):
        with st.spinner("取得中..."):
            try:
                count = sync_pressure(days=pressure_days)
                st.success(f"取得完了: {count}件のデータポイント")
            except Exception as e:
                st.error(f"エラー: {e}")

st.divider()

st.subheader("同期済みデータ確認")
from lib.database import get_conn
with get_conn() as conn:
    sleep_count = conn.execute("SELECT COUNT(*) as c FROM fitbit_sleep").fetchone()["c"]
    hrv_count = conn.execute("SELECT COUNT(*) as c FROM fitbit_hrv WHERE rmssd IS NOT NULL").fetchone()["c"]
    pressure_count = conn.execute("SELECT COUNT(*) as c FROM pressure_log").fetchone()["c"]
    latest_sleep = conn.execute("SELECT date FROM fitbit_sleep ORDER BY date DESC LIMIT 1").fetchone()
    latest_hrv = conn.execute("SELECT date FROM fitbit_hrv ORDER BY date DESC LIMIT 1").fetchone()
    latest_pressure = conn.execute("SELECT timestamp FROM pressure_log ORDER BY timestamp DESC LIMIT 1").fetchone()

c1, c2, c3 = st.columns(3)
c1.metric("睡眠データ", f"{sleep_count}日分",
          delta=latest_sleep["date"] if latest_sleep else "なし")
c2.metric("HRVデータ", f"{hrv_count}日分",
          delta=latest_hrv["date"] if latest_hrv else "なし")
c3.metric("気圧データ", f"{pressure_count}件",
          delta=latest_pressure["timestamp"][:16] if latest_pressure else "なし")
st.divider()
st.subheader("🔍 デバッグ")
if st.button("APIレスポンスを確認"):
    from lib.fitbit import _get_valid_token
    from datetime import datetime as dt2
    import requests
    token = _get_valid_token()
    st.write("トークン存在:", token is not None)
    today = dt2.now().date().strftime("%Y-%m-%d")
    resp = requests.get(
        "https://health.googleapis.com/v4/users/-/sleepSessions",
        headers={"Authorization": f"Bearer {token}"},
        params={
            "startTime": f"{today}T00:00:00Z",
            "endTime": f"{today}T23:59:59Z",
        },
        timeout=10,
    )
    st.write("ステータスコード:", resp.status_code)
    st.write("レスポンス:", resp.text[:2000])
