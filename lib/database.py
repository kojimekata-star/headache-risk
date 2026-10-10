import os
import streamlit as st
from contextlib import contextmanager
from supabase import create_client, Client

def _get_supabase() -> Client:
    url = st.secrets.get("SUPABASE_URL", os.getenv("SUPABASE_URL", ""))
    key = st.secrets.get("SUPABASE_KEY", os.getenv("SUPABASE_KEY", ""))
    return create_client(url, key)

# ===== テナント分離 =====
# patient_id で絞らない全体表（名簿）
GLOBAL_TABLES = {"patients"}

# upsert 時の衝突キー（各表の主キー）
UPSERT_CONFLICT = {
    "fitbit_tokens": "patient_id",
    "fitbit_sleep": "patient_id,date",
    "fitbit_hrv": "patient_id,date",
    "pressure_log": "patient_id,timestamp",
    "settings": "patient_id,key",
}

class TenantContextError(RuntimeError):
    pass

def _tenant_id(table):
    """テナント表なら session の patient_id を返す。未設定なら例外（fail closed）。"""
    if table in GLOBAL_TABLES:
        return None
    pid = st.session_state.get("patient_id")
    if not pid:
        raise TenantContextError("patient_id が未設定です")
    return pid

def _upsert(client, table, data):
    on_conflict = UPSERT_CONFLICT.get(table)
    if on_conflict:
        return client.table(table).upsert(data, on_conflict=on_conflict).execute()
    return client.table(table).upsert(data).execute()

def init_db():
    pass  # Supabaseではテーブルをダッシュボードで作成済み

@contextmanager
def get_conn():
    """SQLite互換のコンテキストマネージャー（Supabase版）"""
    conn = SupabaseConn(_get_supabase())
    try:
        yield conn
        conn.commit()
    except Exception:
        raise

class SupabaseConn:
    def __init__(self, client: Client):
        self.client = client
        self._pending = []

    def commit(self):
        pass

    def rollback(self):
        pass

    def execute(self, sql: str, params=None):
        return SupabaseCursor(self.client, sql, params)

    def executescript(self, sql: str):
        pass

    def executemany(self, sql: str, params_list):
        import re
        table_match = re.search(r'INTO\s+(\w+)', sql, re.IGNORECASE)
        if not table_match:
            return
        table = table_match.group(1).lower()
        pid = _tenant_id(table)

        # 辞書形式のパラメータをupsert（patient_id は session の値で上書き）
        records = []
        for params in params_list:
            if isinstance(params, dict):
                record = dict(params)
                if pid:
                    record["patient_id"] = pid
                records.append(record)

        if records:
            # バッチでupsert（100件ずつ）
            for i in range(0, len(records), 100):
                batch = records[i:i+100]
                _upsert(self.client, table, batch)


class SupabaseRow(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class SupabaseCursor:
    def __init__(self, client: Client, sql: str, params=None):
        self.client = client
        self.sql = sql.strip()
        self.params = params or []
        self._result = None
        self._execute()

    def _execute(self):
        sql = self.sql.upper()

        # SELECT
        if sql.startswith("SELECT"):
            self._result = self._handle_select()
        # INSERT OR REPLACE / INSERT OR IGNORE
        elif sql.startswith("INSERT"):
            self._handle_insert()
        # UPDATE
        elif sql.startswith("UPDATE"):
            self._handle_update()
        # DELETE
        elif sql.startswith("DELETE"):
            self._handle_delete()

    def _table_from_sql(self, sql):
        import re
        m = re.search(r'(?:FROM|INTO|UPDATE)\s+(\w+)', sql, re.IGNORECASE)
        return m.group(1).lower() if m else None

    def _handle_select(self):
        import re
        sql = self.sql
        table = self._table_from_sql(sql)
        if not table:
            return []
        pid = _tenant_id(table)

        query = self.client.table(table).select("*")
        if pid:
            query = query.eq("patient_id", pid)

        # WHERE句の解析
        where = re.search(r'WHERE\s+(.+?)(?:ORDER|LIMIT|$)', sql, re.IGNORECASE | re.DOTALL)
        if where:
            conditions = where.group(1).strip()
            param_idx = 0
            for cond in re.split(r'\bAND\b', conditions, flags=re.IGNORECASE):
                cond = cond.strip()
                if '>=' in cond:
                    col = cond.split('>=')[0].strip().split('.')[-1]
                    val = self.params[param_idx] if param_idx < len(self.params) else cond.split('>=')[1].strip().strip("'\"")
                    query = query.gte(col, val)
                    param_idx += 1
                elif '<=' in cond:
                    col = cond.split('<=')[0].strip().split('.')[-1]
                    val = self.params[param_idx] if param_idx < len(self.params) else cond.split('<=')[1].strip().strip("'\"")
                    query = query.lte(col, val)
                    param_idx += 1
                elif '!=' in cond or 'IS NOT' in cond.upper():
                    col = re.split(r'!=|IS NOT', cond, flags=re.IGNORECASE)[0].strip().split('.')[-1]
                    query = query.not_.is_(col, 'null') if 'NULL' in cond.upper() else query
                    param_idx += 1
                elif 'IS NULL' in cond.upper():
                    col = cond.upper().replace('IS NULL', '').strip().split('.')[-1]
                    query = query.is_(col, 'null')
                elif '=' in cond and 'IS' not in cond.upper():
                    col = cond.split('=')[0].strip().split('.')[-1]
                    val = self.params[param_idx] if param_idx < len(self.params) else cond.split('=')[1].strip().strip("'\"")
                    query = query.eq(col, val)
                    param_idx += 1

        # ORDER BY
        order = re.search(r'ORDER BY\s+(\w+)(?:\s+(ASC|DESC))?', sql, re.IGNORECASE)
        if order:
            col = order.group(1)
            desc = order.group(2) and order.group(2).upper() == 'DESC'
            query = query.order(col, desc=desc)

        # LIMIT
        limit = re.search(r'LIMIT\s+(\d+)', sql, re.IGNORECASE)
        if limit:
            query = query.limit(int(limit.group(1)))

        # COUNT
        if 'COUNT(*)' in sql.upper():
            resp = query.execute()
            count = len(resp.data) if resp.data else 0
            return [SupabaseRow({'c': count})]

        resp = query.execute()
        if not resp.data:
            return []
        if pid:
            # ページ側から見た列構成を従来どおりにする（patient_id は返さない）
            return [SupabaseRow({k: v for k, v in r.items() if k != "patient_id"}) for r in resp.data]
        return [SupabaseRow(r) for r in resp.data]

    def _handle_insert(self):
        import re
        sql = self.sql
        table = self._table_from_sql(sql)
        if not table:
            return
        pid = _tenant_id(table)

        # カラム名取得
        cols_match = re.search(r'\(([^)]+)\)\s*VALUES', sql, re.IGNORECASE)
        if not cols_match:
            return
        cols = [c.strip() for c in cols_match.group(1).split(',')]

        # VALUES取得
        vals_match = re.search(r'VALUES\s*\(([^)]+)\)', sql, re.IGNORECASE)
        if not vals_match:
            return

        params = list(self.params)
        data = {}
        for i, col in enumerate(cols):
            if i < len(params):
                data[col] = params[i]
        if pid:
            data["patient_id"] = pid  # 呼び出し側の値は信用しない

        # INSERT OR REPLACE → upsert
        if 'OR REPLACE' in sql.upper():
            _upsert(self.client, table, data)
        elif 'OR IGNORE' in sql.upper():
            try:
                self.client.table(table).insert(data).execute()
            except Exception:
                pass
        else:
            self.client.table(table).insert(data).execute()

    def _handle_update(self):
        import re
        sql = self.sql
        table = self._table_from_sql(sql)
        if not table:
            return
        pid = _tenant_id(table)

        set_match = re.search(r'SET\s+(.+?)\s+WHERE', sql, re.IGNORECASE | re.DOTALL)
        where_match = re.search(r'WHERE\s+(.+?)$', sql, re.IGNORECASE | re.DOTALL)
        if not set_match or not where_match:
            return

        params = list(self.params)
        param_idx = 0

        set_cols = [s.strip().split('=')[0].strip() for s in set_match.group(1).split(',')]
        data = {}
        for col in set_cols:
            if param_idx < len(params):
                data[col] = params[param_idx]
                param_idx += 1

        where_col = where_match.group(1).split('=')[0].strip()
        where_val = params[param_idx] if param_idx < len(params) else None

        if pid:
            data.pop("patient_id", None)  # 他の患者へ付け替えさせない

        if where_val:
            query = self.client.table(table).update(data).eq(where_col, where_val)
            if pid:
                query = query.eq("patient_id", pid)
            query.execute()

    def _handle_delete(self):
        import re
        sql = self.sql
        table = self._table_from_sql(sql)
        if not table:
            return
        pid = _tenant_id(table)

        where = re.search(r'WHERE\s+(.+?)\s*;?\s*$', sql, re.IGNORECASE | re.DOTALL)
        if not where:
            if pid:
                raise ValueError(f"WHERE のない DELETE は禁止です: {table}")
            raise ValueError(f"WHERE のない DELETE には対応していません: {table}")

        conditions = where.group(1)
        if re.search(r'\bOR\b', conditions, re.IGNORECASE):
            raise ValueError(f"DELETE の条件を解釈できません: {conditions}")

        # col = ? / col = リテラル を AND で連結したものだけ受け付ける
        params = list(self.params)
        param_idx = 0
        eqs = []
        for cond in re.split(r'\bAND\b', conditions, flags=re.IGNORECASE):
            m = re.fullmatch(r'\s*(?:\w+\.)?(\w+)\s*=\s*(\?|-?\d+|\'[^\']*\'|"[^"]*")\s*', cond)
            if not m:
                raise ValueError(f"DELETE の条件を解釈できません: {cond.strip()}")
            col, raw = m.group(1), m.group(2)
            if raw == "?":
                if param_idx >= len(params):
                    raise ValueError("DELETE のパラメータが不足しています")
                val = params[param_idx]
                param_idx += 1
            elif raw[0] in "'\"":
                val = raw[1:-1]
            else:
                val = int(raw)
            eqs.append((col, val))

        query = self.client.table(table).delete()
        for col, val in eqs:
            query = query.eq(col, val)
        if pid:
            query = query.eq("patient_id", pid)
        query.execute()

    def fetchone(self):
        if self._result:
            return self._result[0]
        return None

    def fetchall(self):
        return self._result or []


def get_setting(key: str, default: str = "") -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default

def set_setting(key: str, value: str):
    with get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, value))
