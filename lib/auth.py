import streamlit as st
from lib.database import get_conn


def _logout_button(key: str):
    st.button("ログアウト", on_click=st.logout, key=key)


def require_patient() -> str:
    """ログイン中の Google アカウントを名簿で照合し、patient_id を返す。

    未ログイン・未登録・参加終了の場合は案内を表示して st.stop() する。
    """
    # 前のユーザーの値を持ち越さない
    st.session_state.pop("patient_id", None)

    if not st.user.is_logged_in:
        st.title("🧠 頭痛リスク可視化")
        st.info("このアプリは研究参加者専用です。登録済みのGoogleアカウントでログインしてください。")
        st.button("Googleでログイン", on_click=st.login, type="primary", key="login_button")
        st.stop()

    email = (st.user.email or "").strip().lower()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT patient_id, status FROM patients WHERE google_email=?", (email,)
        ).fetchone()

    if not row:
        st.error("このGoogleアカウントは研究に登録されていません。担当者にご連絡ください。")
        _logout_button("logout_unregistered")
        st.stop()

    if row["status"] != "active":
        st.warning("研究への参加は終了しています。")
        _logout_button("logout_withdrawn")
        st.stop()

    patient_id = row["patient_id"]
    st.session_state["patient_id"] = patient_id
    return patient_id


def render_patient_badge():
    """参加者IDとログアウトを小さく表示する（取り違え防止）。"""
    col_id, col_logout = st.columns([5, 1])
    col_id.caption(f"参加者ID: {st.session_state.get('patient_id', '—')}")
    with col_logout:
        _logout_button("logout_badge")
