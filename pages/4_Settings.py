import streamlit as st
from dotenv import load_dotenv
from lib.database import init_db, get_setting, set_setting

load_dotenv()
init_db()

st.set_page_config(page_title="設定", page_icon="⚙️", layout="wide")
st.title("⚙️ 設定")

st.subheader("位置情報（気圧データ取得用）")

current_lat = get_setting("lat", "35.6762")
current_lon = get_setting("lon", "139.6503")
current_name = get_setting("location_name", "東京")

PRESETS = {
    "東京": (35.6762, 139.6503),
    "大阪": (34.6937, 135.5023),
    "名古屋": (35.1815, 136.9066),
    "札幌": (43.0642, 141.3469),
    "福岡": (33.5904, 130.4017),
    "仙台": (38.2682, 140.8694),
    "カスタム": (None, None),
}

preset = st.selectbox("都市プリセット", list(PRESETS.keys()),
                       index=list(PRESETS.keys()).index(current_name) if current_name in PRESETS else 0)

if preset == "カスタム":
    lat = st.number_input("緯度", value=float(current_lat), format="%.4f")
    lon = st.number_input("経度", value=float(current_lon), format="%.4f")
    location_name = "カスタム"
else:
    lat, lon = PRESETS[preset]
    location_name = preset
    st.info(f"緯度: {lat} / 経度: {lon}")

if st.button("保存", type="primary"):
    set_setting("lat", str(lat))
    set_setting("lon", str(lon))
    set_setting("location_name", location_name)
    st.success(f"保存しました: {location_name} ({lat}, {lon})")

st.divider()

st.subheader("データ管理")
with st.expander("⚠️ データを削除する"):
    col1, col2 = st.columns(2)
    with col1:
        if st.button("FitBitデータをクリア", type="secondary"):
            from lib.database import get_conn
            with get_conn() as conn:
                conn.execute("DELETE FROM fitbit_sleep")
                conn.execute("DELETE FROM fitbit_hrv")
            st.success("FitBitデータを削除しました。")
    with col2:
        if st.button("気圧データをクリア", type="secondary"):
            from lib.database import get_conn
            with get_conn() as conn:
                conn.execute("DELETE FROM pressure_log")
            st.success("気圧データを削除しました。")
