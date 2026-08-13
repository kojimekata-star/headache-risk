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
    # 兵庫県
    "西宮市": (34.7364, 135.3436),
    "神戸市": (34.6901, 135.1956),
    "芦屋市": (34.7281, 135.4036),
    "尼崎市": (34.7335, 135.4071),
    "宝塚市": (34.7985, 135.3592),
    "伊丹市": (34.7855, 135.4011),
    "川西市": (34.8275, 135.4128),
    # 大阪府
    "大阪市": (34.6937, 135.5023),
    "豊中市": (34.7828, 135.4690),
    "吹田市": (34.7653, 135.5154),
    "池田市": (34.8200, 135.4322),
    # 京都府
    "京都市": (35.0116, 135.7681),
    # その他主要都市
    "東京": (35.6762, 139.6503),
    "名古屋": (35.1815, 136.9066),
    "福岡": (33.5904, 130.4017),
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
