"""lib/database.py のテナント分離のテスト（ネットワーク不要）。

supabase クライアントを呼び出し記録用のダミーに、st.session_state を辞書に差し替えて検証する。
"""
from types import SimpleNamespace

import pytest

import lib.database as database
from lib.database import TenantContextError, get_conn


class FakeQuery:
    def __init__(self, client, table):
        self.client = client
        self.table = table
        self.calls = []  # [(method, args, kwargs), ...]
        client.queries.append(self)

    def _rec(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        return self

    def __getattr__(self, name):
        if name in ("select", "insert", "upsert", "update", "delete", "eq", "neq",
                    "gte", "lte", "is_", "order", "limit"):
            return lambda *a, **k: self._rec(name, *a, **k)
        if name == "not_":
            return self._rec("not_")
        raise AttributeError(name)

    def execute(self):
        self.calls.append(("execute", (), {}))
        return SimpleNamespace(data=self.client.rows.get(self.table, []))

    # 検証用ヘルパー
    def eqs(self):
        return [args for name, args, _ in self.calls if name == "eq"]

    def payload(self, method):
        for name, args, kwargs in self.calls:
            if name == method:
                return args[0], kwargs
        return None, None

    def has(self, method):
        return any(name == method for name, _, _ in self.calls)


class FakeClient:
    def __init__(self):
        self.queries = []
        self.rows = {}

    def table(self, name):
        return FakeQuery(self, name)


@pytest.fixture
def env(monkeypatch):
    client = FakeClient()
    session = {}
    monkeypatch.setattr(database, "_get_supabase", lambda: client)
    monkeypatch.setattr(database, "st", SimpleNamespace(session_state=session, secrets={}))
    return SimpleNamespace(client=client, session=session)


def last(env):
    return env.client.queries[-1]


# 1. patient_id 未設定ならテナント表の全操作で TenantContextError
@pytest.mark.parametrize("sql,params", [
    ("SELECT * FROM headache_events", ()),
    ("SELECT COUNT(*) as c FROM fitbit_sleep", ()),
    ("INSERT INTO headache_events (onset_at, intensity) VALUES (?,?)", ("2026-01-01 10:00", 5)),
    ("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", ("lat", "35")),
    ("UPDATE headache_events SET end_at=? WHERE id=?", ("2026-01-01 12:00", 3)),
    ("DELETE FROM medications WHERE id=?", (7,)),
    ("DELETE FROM fitbit_tokens WHERE id=1", ()),
])
def test_no_patient_id_raises(env, sql, params):
    with pytest.raises(TenantContextError):
        with get_conn() as conn:
            conn.execute(sql, params)
    assert env.client.queries == []


def test_no_patient_id_executemany_raises(env):
    with pytest.raises(TenantContextError):
        with get_conn() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO pressure_log (timestamp, pressure_hpa, lat, lon) "
                "VALUES (:timestamp, :pressure_hpa, :lat, :lon)",
                [{"timestamp": "2026-01-01T00:00", "pressure_hpa": 1010, "lat": 1, "lon": 2}],
            )
    assert env.client.queries == []


def test_empty_patient_id_raises(env):
    env.session["patient_id"] = ""
    with pytest.raises(TenantContextError):
        with get_conn() as conn:
            conn.execute("SELECT * FROM fitbit_tokens")


# 2. SELECT に eq("patient_id", pid) が必ず付く（COUNT を含む）
@pytest.mark.parametrize("sql,params", [
    ("SELECT * FROM fitbit_tokens", ()),
    ("SELECT id, onset_at FROM headache_events ORDER BY onset_at DESC LIMIT 50", ()),
    ("SELECT value FROM settings WHERE key=?", ("lat",)),
    ("SELECT COUNT(*) as c FROM fitbit_sleep", ()),
    ("SELECT COUNT(*) as c FROM fitbit_hrv WHERE resting_hr IS NOT NULL", ()),
])
def test_select_filtered_by_patient(env, sql, params):
    env.session["patient_id"] = "P01"
    with get_conn() as conn:
        conn.execute(sql, params).fetchall()
    q = last(env)
    assert q.table in sql.lower()
    assert ("patient_id", "P01") in q.eqs()
    assert q.has("execute")


def test_select_keeps_other_conditions(env):
    env.session["patient_id"] = "P01"
    with get_conn() as conn:
        conn.execute("SELECT value FROM settings WHERE key=?", ("lat",))
    assert last(env).eqs() == [("patient_id", "P01"), ("key", "lat")]


def test_count_returns_filtered_count(env):
    env.session["patient_id"] = "P01"
    env.client.rows["fitbit_sleep"] = [{"patient_id": "P01", "date": "d1"}, {"patient_id": "P01", "date": "d2"}]
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) as c FROM fitbit_sleep").fetchone()
    assert row["c"] == 2
    assert ("patient_id", "P01") in last(env).eqs()


# 3. INSERT / executemany / upsert に patient_id が session の値で入る
def test_insert_injects_patient_id(env):
    env.session["patient_id"] = "P01"
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO headache_events (onset_at, end_at, intensity, notes) VALUES (?,?,?,?)",
            ("2026-01-01 10:00", None, 5, None),
        )
    data, _ = last(env).payload("insert")
    assert data["patient_id"] == "P01"
    assert data["onset_at"] == "2026-01-01 10:00"


def test_insert_overrides_caller_patient_id(env):
    env.session["patient_id"] = "P01"
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO headache_events (patient_id, onset_at) VALUES (?,?)",
            ("P99", "2026-01-01 10:00"),
        )
    data, _ = last(env).payload("insert")
    assert data["patient_id"] == "P01"


@pytest.mark.parametrize("sql,params,table,conflict", [
    ("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", ("lat", "35"), "settings", "patient_id,key"),
    ("INSERT OR REPLACE INTO fitbit_tokens (access_token, refresh_token, expires_at, fitbit_user_id) VALUES (?,?,?,?)",
     ("a", "r", 1, ""), "fitbit_tokens", "patient_id"),
    ("INSERT OR REPLACE INTO fitbit_sleep (date, duration_min) VALUES (?,?)", ("2026-01-01", 400),
     "fitbit_sleep", "patient_id,date"),
    ("INSERT OR REPLACE INTO fitbit_hrv (patient_id, date, resting_hr) VALUES (?,?,?)", ("P99", "2026-01-01", 60),
     "fitbit_hrv", "patient_id,date"),
])
def test_upsert_injects_patient_id_and_conflict(env, sql, params, table, conflict):
    env.session["patient_id"] = "P01"
    with get_conn() as conn:
        conn.execute(sql, params)
    q = last(env)
    assert q.table == table
    data, kwargs = q.payload("upsert")
    assert data["patient_id"] == "P01"
    assert kwargs.get("on_conflict") == conflict


def test_insert_or_ignore_injects_patient_id(env):
    env.session["patient_id"] = "P01"
    with get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?,?)", ("lat", "35"))
    data, _ = last(env).payload("insert")
    assert data["patient_id"] == "P01"


def test_executemany_injects_patient_id(env):
    env.session["patient_id"] = "P02"
    records = [
        {"timestamp": "2026-01-01T00:00", "pressure_hpa": 1010, "lat": 1, "lon": 2},
        {"timestamp": "2026-01-01T01:00", "pressure_hpa": 1011, "lat": 1, "lon": 2, "patient_id": "P99"},
    ]
    with get_conn() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO pressure_log (timestamp, pressure_hpa, lat, lon) "
            "VALUES (:timestamp, :pressure_hpa, :lat, :lon)",
            records,
        )
    q = last(env)
    batch, kwargs = q.payload("upsert")
    assert [r["patient_id"] for r in batch] == ["P02", "P02"]
    assert kwargs.get("on_conflict") == "patient_id,timestamp"
    # 呼び出し側の dict は書き換えない
    assert "patient_id" not in records[0]
    assert records[1]["patient_id"] == "P99"


# 4. UPDATE に patient_id 条件が付く
def test_update_filtered_by_patient(env):
    env.session["patient_id"] = "P01"
    with get_conn() as conn:
        conn.execute("UPDATE headache_events SET end_at=? WHERE id=?", ("2026-01-01 12:00", 3))
    q = last(env)
    data, _ = q.payload("update")
    assert data == {"end_at": "2026-01-01 12:00"}
    assert ("id", 3) in q.eqs()
    assert ("patient_id", "P01") in q.eqs()


def test_update_cannot_move_row_to_other_patient(env):
    env.session["patient_id"] = "P01"
    with get_conn() as conn:
        conn.execute("UPDATE headache_events SET patient_id=?, notes=? WHERE id=?", ("P99", "x", 3))
    q = last(env)
    data, _ = q.payload("update")
    assert "patient_id" not in data
    assert ("patient_id", "P01") in q.eqs()


# 5. DELETE ... WHERE id=1（params なし）でも全行削除にならない
def test_delete_literal_where_not_delete_all(env):
    env.session["patient_id"] = "P01"
    with get_conn() as conn:
        conn.execute("DELETE FROM fitbit_tokens WHERE id=1")
    q = last(env)
    assert q.has("delete")
    assert not q.has("neq")
    assert sorted(q.eqs()) == [("id", 1), ("patient_id", "P01")]


def test_delete_param_where(env):
    env.session["patient_id"] = "P01"
    with get_conn() as conn:
        conn.execute("DELETE FROM medications WHERE id=?", (7,))
    q = last(env)
    assert not q.has("neq")
    assert sorted(q.eqs()) == [("id", 7), ("patient_id", "P01")]


def test_delete_multiple_conditions_and_string_literal(env):
    env.session["patient_id"] = "P01"
    with get_conn() as conn:
        conn.execute("DELETE FROM settings WHERE key = 'lat' AND value = ?", ("35",))
    assert sorted(last(env).eqs()) == [("key", "lat"), ("patient_id", "P01"), ("value", "35")]


@pytest.mark.parametrize("sql,params", [
    ("DELETE FROM headache_events WHERE id < ?", (5,)),
    ("DELETE FROM headache_events WHERE id = ? OR 1=1", (5,)),
    ("DELETE FROM headache_events WHERE id IN (1,2)", ()),
    ("DELETE FROM headache_events WHERE id = ?", ()),
])
def test_delete_unparseable_where_raises(env, sql, params):
    env.session["patient_id"] = "P01"
    with pytest.raises(ValueError):
        with get_conn() as conn:
            conn.execute(sql, params)
    assert not any(q.has("execute") for q in env.client.queries)


# 6. WHERE なしの DELETE は ValueError
@pytest.mark.parametrize("sql", ["DELETE FROM fitbit_tokens", "DELETE FROM headache_events;"])
def test_delete_without_where_raises(env, sql):
    env.session["patient_id"] = "P01"
    with pytest.raises(ValueError):
        with get_conn() as conn:
            conn.execute(sql)
    assert not any(q.has("execute") for q in env.client.queries)


# 7. patients 表は patient_id で絞られない（ログイン前でも引ける）
def test_patients_table_not_filtered(env):
    env.client.rows["patients"] = [{"patient_id": "P01", "status": "active"}]
    with get_conn() as conn:
        row = conn.execute(
            "SELECT patient_id, status FROM patients WHERE google_email=?", ("a@example.com",)
        ).fetchone()
    q = last(env)
    assert q.table == "patients"
    assert q.eqs() == [("google_email", "a@example.com")]
    # 名簿表の結果からは patient_id を除去しない
    assert row["patient_id"] == "P01"


# 8. セッションが切り替わると直後のクエリは新しい patient_id で絞られる
def test_session_switch(env):
    env.session["patient_id"] = "P01"
    with get_conn() as conn:
        conn.execute("SELECT * FROM headache_events")
    assert ("patient_id", "P01") in last(env).eqs()

    env.session["patient_id"] = "P02"
    with get_conn() as conn:
        conn.execute("SELECT * FROM headache_events")
        conn.execute("INSERT INTO headache_events (onset_at) VALUES (?)", ("2026-01-02 09:00",))
    select_q, insert_q = env.client.queries[-2], env.client.queries[-1]
    assert ("patient_id", "P02") in select_q.eqs()
    assert ("patient_id", "P01") not in select_q.eqs()
    assert insert_q.payload("insert")[0]["patient_id"] == "P02"


def test_setting_helpers_are_per_patient(env):
    env.session["patient_id"] = "P03"
    database.set_setting("lat", "34.7")
    data, kwargs = last(env).payload("upsert")
    assert data == {"key": "lat", "value": "34.7", "patient_id": "P03"}
    database.get_setting("lat")
    assert ("patient_id", "P03") in last(env).eqs()


# 9. テナント表の SELECT 結果に patient_id が含まれない
def test_select_result_strips_patient_id(env):
    env.session["patient_id"] = "P01"
    env.client.rows["headache_events"] = [
        {"id": 1, "patient_id": "P01", "onset_at": "2026-01-01 10:00", "intensity": 5},
        {"id": 2, "patient_id": "P01", "onset_at": "2026-01-02 10:00", "intensity": 3},
    ]
    with get_conn() as conn:
        rows = conn.execute("SELECT id, onset_at, intensity FROM headache_events").fetchall()
        one = conn.execute("SELECT id, onset_at, intensity FROM headache_events").fetchone()
    assert all("patient_id" not in dict(r) for r in rows)
    assert "patient_id" not in dict(one)
    assert dict(rows[0]) == {"id": 1, "onset_at": "2026-01-01 10:00", "intensity": 5}
    # 位置インデックスアクセスも従来の列順のまま
    assert one[0] == 1
