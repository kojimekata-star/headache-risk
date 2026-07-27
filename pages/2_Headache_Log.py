import streamlit as st
from datetime import datetime, date, time as dtime, timezone, timedelta

JST = timezone(timedelta(hours=9))

def now_jst():
    return datetime.now(JST).replace(tzinfo=None)
from dotenv import load_dotenv
from lib.database import init_db, get_conn

load_dotenv()
init_db()

st.set_page_config(page_title="頭痛記録", page_icon="🤕", layout="wide")
st.title("🤕 頭痛・服薬記録")

COMMON_DRUGS = [
    "ロキソプロフェン（ロキソニン）",
    "イブプロフェン",
    "アセトアミノフェン（カロナール）",
    "ナプロキセン",
    "スマトリプタン（イミグラン）",
    "エレトリプタン（レルパックス）",
    "リザトリプタン（マクサルト）",
    "ゾルミトリプタン（ゾーミッグ）",
    "その他（下に入力）",
]

COMMON_DOSES = {
    "ロキソプロフェン（ロキソニン）": [(60, "mg"), (120, "mg")],
    "イブプロフェン": [(200, "mg"), (400, "mg"), (600, "mg")],
    "アセトアミノフェン（カロナール）": [(200, "mg"), (500, "mg"), (1000, "mg")],
    "スマトリプタン（イミグラン）": [(50, "mg"), (100, "mg")],
    "エレトリプタン（レルパックス）": [(20, "mg"), (40, "mg")],
    "リザトリプタン（マクサルト）": [(10, "mg")],
    "ゾルミトリプタン（ゾーミッグ）": [(2.5, "mg"), (5, "mg")],
}


def load_events():
    with get_conn() as conn:
        return conn.execute("""
            SELECT id, onset_at, end_at, intensity, notes
            FROM headache_events
            ORDER BY onset_at DESC
            LIMIT 50
        """).fetchall()


def load_meds(event_id: int):
    with get_conn() as conn:
        return conn.execute("""
            SELECT id, drug_name, dose_amount, dose_unit, taken_at
            FROM medications
            WHERE headache_event_id = ?
            ORDER BY taken_at
        """, (event_id,)).fetchall()


def delete_med(med_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM medications WHERE id=?", (med_id,))


# ====== New event form ======
with st.expander("➕ 新しい頭痛を記録", expanded=st.session_state.get("open_new", False)):
    with st.form("new_event"):
        col1, col2 = st.columns(2)
        with col1:
            onset_date = st.date_input("発症日", value=now_jst().date())
            onset_time = st.time_input("発症時刻", value=dtime(now_jst().hour, now_jst().minute), step=60)
        with col2:
            add_end = st.checkbox("終了時刻も入力する")
            if add_end:
                end_date = st.date_input("終了日", value=now_jst().date(), key="end_d")
                end_time = st.time_input("終了時刻", value=dtime(now_jst().hour, now_jst().minute), step=60, key="end_t")
            
        intensity = st.slider("強度", 1, 10, 5, help="1=軽微、10=最大")
        notes = st.text_area("メモ（前兆・状況など）", height=80)

        if st.form_submit_button("記録する", type="primary"):
            onset_at = datetime.combine(onset_date, onset_time).strftime("%Y-%m-%d %H:%M")
            end_at = None
            if add_end:
                end_at = datetime.combine(end_date, end_time).strftime("%Y-%m-%d %H:%M")
            with get_conn() as conn:
                conn.execute(
                    "INSERT INTO headache_events (onset_at, end_at, intensity, notes) VALUES (?,?,?,?)",
                    (onset_at, end_at, intensity, notes or None),
                )
            st.session_state["open_new"] = False
            st.success("記録しました。")
            st.rerun()

st.divider()
st.subheader("記録一覧")

events = load_events()
if not events:
    st.info("まだ記録がありません。")
else:
    for ev in events:
        ev = dict(ev)
        onset_dt = datetime.strptime(ev["onset_at"], "%Y-%m-%d %H:%M")
        end_str = ev["end_at"] or "進行中"
        status_icon = "✅" if ev["end_at"] else "🔴"
        header = f"{status_icon} {onset_dt.strftime('%Y/%m/%d %H:%M')}  強度{ev['intensity'] or '—'}/10  〜 {end_str}"

        with st.expander(header):
            if ev["notes"]:
                st.caption(f"メモ: {ev['notes']}")

            col_a, col_b = st.columns(2)

            # --- End time ---
            with col_a:
                if not ev["end_at"]:
                    with st.form(f"end_{ev['id']}"):
                        end_d = st.date_input("終了日", value=now_jst().date(), key=f"ed_{ev['id']}")
                        end_t = st.time_input("終了時刻", value=dtime(now_jst().hour, now_jst().minute), step=60, key=f"et_{ev['id']}")
                        if st.form_submit_button("終了を記録"):
                            end_at = datetime.combine(end_d, end_t).strftime("%Y-%m-%d %H:%M")
                            with get_conn() as conn:
                                conn.execute("UPDATE headache_events SET end_at=? WHERE id=?",
                                             (end_at, ev["id"]))
                            st.rerun()

            # --- Medications ---
            with col_b:
                meds = load_meds(ev["id"])
                if meds:
                    st.markdown("**服薬記録**")
                    for med in meds:
                        med = dict(med)
                        taken = datetime.strptime(med["taken_at"], "%Y-%m-%d %H:%M").strftime("%H:%M")
                        line = f"・{taken} {med['drug_name']}"
                        if med["dose_amount"]:
                            line += f" {med['dose_amount']}{med['dose_unit']}"
                        col_m1, col_m2 = st.columns([5, 1])
                        col_m1.markdown(line)
                        if col_m2.button("✕", key=f"del_med_{med['id']}"):
                            delete_med(med["id"])
                            st.rerun()

            # Add medication form
            with st.form(f"med_{ev['id']}"):
                st.markdown("**服薬を追加**")
                c1, c2, c3 = st.columns(3)
                with c1:
                    drug_sel = st.selectbox("薬", COMMON_DRUGS, key=f"drug_{ev['id']}")
                    if drug_sel == "その他（下に入力）":
                        drug_name = st.text_input("薬名を入力", key=f"drug_custom_{ev['id']}")
                    else:
                        drug_name = drug_sel
                with c2:
                    if drug_sel in COMMON_DOSES:
                        preset_doses = [f"{d}{u}" for d, u in COMMON_DOSES[drug_sel]]
                        dose_sel = st.selectbox("用量", preset_doses + ["その他"], key=f"dose_sel_{ev['id']}")
                        if dose_sel == "その他":
                            dose_amount = st.number_input("mg", min_value=0.0, key=f"dose_n_{ev['id']}")
                            dose_unit = "mg"
                        else:
                            dose_amount = float(dose_sel.replace("mg", ""))
                            dose_unit = "mg"
                    else:
                        dose_amount = st.number_input("量", min_value=0.0, key=f"dose_n_{ev['id']}")
                        dose_unit = st.selectbox("単位", ["mg", "錠", "包"], key=f"unit_{ev['id']}")
                with c3:
                    taken_d = st.date_input("日付", value=now_jst().date(), key=f"td_{ev['id']}")
                    taken_t = st.time_input("時刻", value=dtime(now_jst().hour, now_jst().minute), step=60, key=f"tt_{ev['id']}")
                if st.form_submit_button("服薬を追加"):
                    if drug_name:
                        taken_at = datetime.combine(taken_d, taken_t).strftime("%Y-%m-%d %H:%M")
                        with get_conn() as conn:
                            conn.execute("""
                                INSERT INTO medications (headache_event_id, drug_name, dose_amount, dose_unit, taken_at)
                                VALUES (?,?,?,?,?)
                            """, (ev["id"], drug_name, dose_amount or None, dose_unit, taken_at))
                        st.rerun()
                    else:
                        st.warning("薬名を入力してください。")

            # Delete event
            if st.button("🗑 この記録を削除", key=f"del_ev_{ev['id']}"):
                with get_conn() as conn:
                    conn.execute("DELETE FROM headache_events WHERE id=?", (ev["id"],))
                st.rerun()
