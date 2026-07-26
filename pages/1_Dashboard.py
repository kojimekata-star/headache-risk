import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
from lib.database import init_db, get_conn
from lib.risk import compute_risk, compute_risk_history
from lib.pressure import get_recent_pressure, compute_pressure_features

load_dotenv()
init_db()

st.set_page_config(page_title="ダッシュボード", page_icon="📊", layout="wide")
st.title("📊 ダッシュボード")

today = datetime.now().strftime("%Y-%m-%d")
risk = compute_risk(today)

# --- Top: Risk gauge ---
col_gauge, col_factors = st.columns([1, 2])

with col_gauge:
    total = risk["total"]
    if total < 30:
        color, label = "#2ecc71", "低リスク"
    elif total < 60:
        color, label = "#f39c12", "中リスク"
    elif total < 80:
        color, label = "#e67e22", "高リスク"
    else:
        color, label = "#e74c3c", "要注意"

    fig_gauge = go.Figure(go.Indicator(
        mode="gauge+number",
        value=total,
        title={"text": f"本日のリスク<br><span style='font-size:0.8em'>{label}</span>"},
        gauge={
            "axis": {"range": [0, 100]},
            "bar": {"color": color},
            "steps": [
                {"range": [0, 30], "color": "#d5f5e3"},
                {"range": [30, 60], "color": "#fef9e7"},
                {"range": [60, 80], "color": "#fdebd0"},
                {"range": [80, 100], "color": "#fadbd8"},
            ],
            "threshold": {"line": {"color": "red", "width": 4}, "thickness": 0.75, "value": 80},
        },
    ))
    fig_gauge.update_layout(height=280, margin=dict(t=40, b=0, l=20, r=20))
    st.plotly_chart(fig_gauge, use_container_width=True)

with col_factors:
    st.subheader("要因別スコア")
    factors = {
        "😴 睡眠逸脱": risk["sleep"],
        "💓 自律神経(HRV)": risk["hrv"],
        "🌪 気圧変動": risk["pressure"],
    }
    fig_bar = go.Figure(go.Bar(
        x=list(factors.values()),
        y=list(factors.keys()),
        orientation="h",
        marker_color=["#3498db", "#9b59b6", "#1abc9c"],
        text=[f"{v}点" for v in factors.values()],
        textposition="outside",
    ))
    fig_bar.update_layout(
        xaxis={"range": [0, 100], "title": "スコア（0〜100）"},
        height=220,
        margin=dict(t=10, b=10, l=10, r=60),
    )
    st.plotly_chart(fig_bar, use_container_width=True)

    st.caption("各スコアは個人の平常値からの乖離量。高いほど平常状態から逸脱しています。")

st.divider()

# --- Pressure trend ---
col_pres, col_sleep = st.columns(2)

with col_pres:
    st.subheader("🌪 気圧推移（過去48時間）")
    pressure_rows = get_recent_pressure(hours=48)
    if pressure_rows:
        df_pres = pd.DataFrame(pressure_rows)
        df_pres["timestamp"] = pd.to_datetime(df_pres["timestamp"])
        features = compute_pressure_features()

        fig_pres = px.line(df_pres, x="timestamp", y="pressure_hpa",
                           labels={"timestamp": "", "pressure_hpa": "気圧 (hPa)"})
        fig_pres.update_layout(height=220, margin=dict(t=10, b=10))
        st.plotly_chart(fig_pres, use_container_width=True)

        c1, c2, c3 = st.columns(3)
        c1.metric("現在", f"{features['current']} hPa" if features['current'] else "—")
        c2.metric("3h変化", f"{features['change_3h']:+.1f}" if features['change_3h'] is not None else "—")
        c3.metric("6h変化", f"{features['change_6h']:+.1f}" if features['change_6h'] is not None else "—")
    else:
        st.info("気圧データがありません。FitBitページからデータを同期してください。")

with col_sleep:
    st.subheader("😴 最近の睡眠")
    with get_conn() as conn:
        sleep_rows = conn.execute("""
            SELECT date, duration_min, efficiency, deep_min, rem_min
            FROM fitbit_sleep ORDER BY date DESC LIMIT 7
        """).fetchall()

    if sleep_rows:
        df_sleep = pd.DataFrame([dict(r) for r in sleep_rows])
        df_sleep["日付"] = pd.to_datetime(df_sleep["date"]).dt.strftime("%m/%d")
        df_sleep["睡眠時間(h)"] = (df_sleep["duration_min"] / 60).round(1)

        fig_sleep = go.Figure()
        fig_sleep.add_bar(x=df_sleep["日付"], y=df_sleep["睡眠時間(h)"],
                          name="睡眠時間", marker_color="#3498db")
        fig_sleep.update_layout(height=220, margin=dict(t=10, b=10),
                                 yaxis_title="時間 (h)")
        st.plotly_chart(fig_sleep, use_container_width=True)
    else:
        st.info("睡眠データがありません。")

st.divider()

# --- 30-day timeline ---
st.subheader("📈 30日間の推移")

history = compute_risk_history(days=30)
df_hist = pd.DataFrame(history)
df_hist["date"] = pd.to_datetime(df_hist["date"])

from datetime import timedelta
thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
with get_conn() as conn:
    event_rows = conn.execute("""
        SELECT onset_at, end_at, intensity FROM headache_events
        WHERE onset_at >= ?
        ORDER BY onset_at
    """, (thirty_days_ago,)).fetchall()

fig_hist = go.Figure()

# Risk score line
fig_hist.add_scatter(
    x=df_hist["date"], y=df_hist["total"],
    mode="lines+markers", name="リスクスコア",
    line=dict(color="#3498db", width=2),
    marker=dict(size=5),
)

# Background fill by risk level
fig_hist.add_hrect(y0=0, y1=30, fillcolor="#d5f5e3", opacity=0.2, line_width=0)
fig_hist.add_hrect(y0=30, y1=60, fillcolor="#fef9e7", opacity=0.2, line_width=0)
fig_hist.add_hrect(y0=60, y1=80, fillcolor="#fdebd0", opacity=0.2, line_width=0)
fig_hist.add_hrect(y0=80, y1=100, fillcolor="#fadbd8", opacity=0.2, line_width=0)

# Headache events
for ev in event_rows:
    onset = pd.to_datetime(ev["onset_at"])
    intensity = ev["intensity"] or 5
    fig_hist.add_scatter(
        x=[onset], y=[95],
        mode="markers+text",
        marker=dict(symbol="triangle-down", size=12 + intensity, color="#e74c3c"),
        text=[f"強度{intensity}"],
        textposition="top center",
        name="頭痛発生",
        showlegend=False,
    )

fig_hist.update_layout(
    yaxis={"range": [0, 105], "title": "スコア"},
    xaxis={"title": ""},
    height=320,
    margin=dict(t=10, b=10),
    legend=dict(orientation="h", y=1.05),
)
st.plotly_chart(fig_hist, use_container_width=True)
st.caption("▼ マーカーが頭痛発作。サイズは強度に比例。")
st.divider()

# --- CSV Export ---
st.subheader("📥 データエクスポート")

with get_conn() as conn:
    df_export_sleep = pd.DataFrame([dict(r) for r in conn.execute("""
        SELECT date, duration_min, deep_min, light_min, rem_min, wake_min
        FROM fitbit_sleep ORDER BY date DESC
    """).fetchall()])

    df_export_hrv = pd.DataFrame([dict(r) for r in conn.execute("""
        SELECT date, resting_hr FROM fitbit_hrv
        WHERE resting_hr IS NOT NULL ORDER BY date DESC
    """).fetchall()])

    df_export_headache = pd.DataFrame([dict(r) for r in conn.execute("""
        SELECT id, onset_at, end_at, intensity, notes
        FROM headache_events
        ORDER BY onset_at DESC
    """).fetchall()])

    df_export_medications = pd.DataFrame([dict(r) for r in conn.execute("""
        SELECT headache_event_id, drug_name, dose_amount, dose_unit, taken_at
        FROM medications
        ORDER BY taken_at DESC
    """).fetchall()])

    df_export_pressure = pd.DataFrame([dict(r) for r in conn.execute("""
        SELECT timestamp, pressure_hpa FROM pressure_log
        ORDER BY timestamp DESC LIMIT 1000
    """).fetchall()])

# 頭痛記録と服薬記録を結合
if not df_export_headache.empty and not df_export_medications.empty:
    df_export_headache = pd.merge(
        df_export_headache, df_export_medications,
        left_on="id", right_on="headache_event_id",
        how="left"
    ).drop(columns=["headache_event_id"], errors="ignore")

# 結合データ（日付ベース）
if not df_export_sleep.empty and not df_export_hrv.empty:
    df_combined = pd.merge(df_export_sleep, df_export_hrv, on="date", how="outer").sort_values("date", ascending=False)
elif not df_export_sleep.empty:
    df_combined = df_export_sleep
else:
    df_combined = df_export_hrv if not df_export_hrv.empty else pd.DataFrame()

col_dl1, col_dl2, col_dl3, col_dl4 = st.columns(4)

with col_dl1:
    st.download_button(
        "😴 睡眠・心拍CSV",
        df_combined.to_csv(index=False, encoding="utf-8-sig") if not df_combined.empty else "",
        file_name=f"sleep_hrv_{today}.csv",
        mime="text/csv",
        disabled=df_combined.empty,
    )

with col_dl2:
    st.download_button(
        "🤕 頭痛記録CSV",
        df_export_headache.to_csv(index=False, encoding="utf-8-sig") if not df_export_headache.empty else "",
        file_name=f"headache_{today}.csv",
        mime="text/csv",
        disabled=df_export_headache.empty,
    )

with col_dl3:
    st.download_button(
        "🌪 気圧データCSV",
        df_export_pressure.to_csv(index=False, encoding="utf-8-sig") if not df_export_pressure.empty else "",
        file_name=f"pressure_{today}.csv",
        mime="text/csv",
        disabled=df_export_pressure.empty,
    )
with col_dl4:
    # 全データ結合
    risk_history = compute_risk_history(days=30)
    df_risk = pd.DataFrame(risk_history)
    st.download_button(
        "📊 リスクスコアCSV",
        df_risk.to_csv(index=False, encoding="utf-8-sig"),
        file_name=f"risk_score_{today}.csv",
        mime="text/csv",
    )
