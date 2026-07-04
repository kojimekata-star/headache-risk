import os
import streamlit as st
from dotenv import load_dotenv
from lib.database import init_db
from lib.fitbit import get_tokens, get_auth_url, exchange_code, save_tokens

load_dotenv()
init_db()

st.set_page_config(page_title="頭痛リスク", page_icon="🧠", layout="wide")

# FitBit OAuth callback
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

fitbit_connected = get_tokens() is not None
client_id_set = bool(os.getenv("FITBIT_CLIENT_ID"))

st.title("🧠 頭痛リスク可視化")
st.caption("睡眠・自律神経・気圧・生活リズムから個人内の頭痛リスクをスコア化します")

st.divider()

col1, col2 = st.columns(2)
with col1:
    st.metric("FitBit", "✅ 連携済" if fitbit_connected else "❌ 未連携")
with col2:
    st.metric("APIキー", "✅ 設定済" if client_id_set else "❌ 未設定")

st.divider()

if not client_id_set:
    st.info("""
    **セットアップ手順**
    1. [dev.fitbit.com](https://dev.fitbit.com) で開発者アカウントを作成
    2. "Register an App" → アプリ種別: **Personal**
    3. Callback URL: `https://kojimekata-star-headache-risk-home-xwpblk.streamlit.app`
    4. 取得した Client ID と Client Secret を `.env` ファイルに記入
    5. アプリを再起動
    """)
elif not fitbit_connected:
    st.warning("FitBitとの連携が必要です。")
    if st.button("⌚ FitBitと連携する", type="primary"):
        auth_url = get_auth_url()
        st.markdown(f"[こちらをクリックして認証]({auth_url})")

st.subheader("ページ")
st.page_link("pages/1_Dashboard.py", label="📊 ダッシュボード — 本日のリスクスコアと推移")
st.page_link("pages/2_Headache_Log.py", label="🤕 頭痛を記録 — 発症・終了・服薬")
st.page_link("pages/3_FitBit.py", label="⌚ FitBit — 連携・データ同期")
st.page_link("pages/4_Settings.py", label="⚙️ 設定 — 位置情報")
