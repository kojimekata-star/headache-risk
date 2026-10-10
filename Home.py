import streamlit as st
from datetime import datetime, timedelta
from lib.database import init_db
from lib.auth import require_patient, render_patient_badge
from lib.fitbit import get_tokens, get_auth_url, exchange_code, save_tokens, is_connected, sync_sleep, sync_hrv
from lib.pressure import sync_pressure

init_db()

st.set_page_config(page_title="頭痛リスク", page_icon="🧠", layout="wide")

pid = require_patient()
render_patient_badge()

# Google OAuth callback
params = st.query_params
if "code" in params:
    code = params["code"]
    try:
        token_data = exchange_code(code)
        save_tokens(token_data)
        st.query_params.clear()
        st.success("✅ Google Healthとの連携が完了しました。")
        st.rerun()
    except Exception as e:
        st.error(f"認証エラー: {e}")

has_tokens = get_tokens() is not None
fitbit_connected = is_connected()
client_id_set = bool(st.secrets.get("GOOGLE_CLIENT_ID", ""))

st.title("🧠 頭痛リスク可視化")
st.caption("睡眠・自律神経・気圧・生活リズムから個人内の頭痛リスクをスコア化します")
st.divider()

col1, col2 = st.columns(2)
with col1:
    st.metric("FitBit", "✅ 連携済" if fitbit_connected else "❌ 未連携")
with col2:
    st.metric("APIキー", "✅ 設定済" if client_id_set else "❌ 未設定")

st.divider()

# 自動同期（一時無効化）
# if fitbit_connected:
#     today = datetime.now().strftime("%Y-%m-%d")
#     yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
#     with st.spinner("データを自動同期中..."):
#         try:
#             sync_sleep(yesterday)
#             sync_hrv(yesterday)
#             sync_pressure(days=1)
#             st.success(f"✅ 自動同期完了（{yesterday}）")
#         except Exception as e:
#             st.warning(f"自動同期でエラーが発生しました: {e}")

st.divider()

if not client_id_set:
    st.info("""
    **セットアップ手順**
    1. Google Cloud Console でGoogle Health APIを有効化
    2. OAuth クライアントIDを作成
    3. Streamlit Cloud の Secrets に設定
    """)
else:
    # 再認証すると save_tokens が上書きするので、トークンは削除しない
    auth_url = get_auth_url(login_hint=st.user.email)
    if fitbit_connected:
        st.link_button("🔄 連携を更新する（毎週日曜に押してください）", auth_url)
    else:
        if has_tokens:
            st.warning("連携の有効期限が切れています。下のボタンから再連携してください。")
        else:
            st.warning("Google Healthとの連携が必要です。")
        st.link_button("⌚ Google Healthと連携する", auth_url, type="primary")

st.subheader("ページ")
st.page_link("pages/1_Dashboard.py", label="📊 ダッシュボード — 本日のリスクスコアと推移")
st.page_link("pages/2_Headache_Log.py", label="🤕 頭痛を記録 — 発症・終了・服薬")
st.page_link("pages/3_FitBit.py", label="⌚ FitBit — 連携・データ同期")
st.page_link("pages/4_Settings.py", label="⚙️ 設定 — 位置情報")
