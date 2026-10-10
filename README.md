# 頭痛リスク可視化アプリ（マルチテナント版）

全患者が同一URL・同一Supabaseを使う。患者は Google でログインし（`st.login()`）、名簿 `patients` に登録された `active` の患者だけが自分のデータを読み書きできる。

- テナントキーは研究用患者ID（`P01` 等）。データ表は `patient_id` のみを持ち、メールアドレスは `patients` 表にだけ置く。
- テナント分離は `lib/database.py`（DBアクセスの単一窓口）で行う。`patient_id` が無い状態でテナント表にアクセスすると `TenantContextError`（fail closed）。
- Google Health 連携は独自OAuth（`lib/fitbit.py`）。トークンは患者別に `fitbit_tokens` に保存する。

## 1. Supabase

新しいプロジェクトの SQL Editor で `schema_multitenant.sql` を実行する。全表で RLS を有効化し、ポリシーは作らない（アプリは secret キーで接続するため動作し、publishable キーでは読み書きできない）。

## 2. Secrets（Streamlit Cloud の Secrets / ローカルは `.streamlit/secrets.toml`）

値はリポジトリに書かないこと。

```toml
GOOGLE_CLIENT_ID = "..."
GOOGLE_CLIENT_SECRET = "..."
GOOGLE_REDIRECT_URI = "https://<APP>.streamlit.app"   # Health連携用（従来どおり）
SUPABASE_URL = "https://<ref>.supabase.co"
SUPABASE_KEY = "sb_secret_..."

[auth]                                                 # ログイン（st.login）用
redirect_uri = "https://<APP>.streamlit.app/oauth2callback"
cookie_secret = "<ランダムな32文字以上>"
client_id = "（GOOGLE_CLIENT_ID と同じ）"
client_secret = "（GOOGLE_CLIENT_SECRET と同じ）"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```

## 3. Google Cloud

OAuth クライアントの「承認済みのリダイレクト URI」に次の2つを登録する。

- `https://<APP>.streamlit.app`（Google Health 連携の戻り先）
- `https://<APP>.streamlit.app/oauth2callback`（ログインの戻り先）

OAuth 同意画面が「テスト」状態の間は、患者の Google アカウントをテストユーザーに登録する必要がある。またリフレッシュトークンが約7日で失効するため、患者には毎週日曜に「🔄 連携を更新する」を押してもらう。

## 4. 運用SQL（Supabase の SQL Editor）

患者登録（メールは小文字・Googleが返す表記で登録）：

```sql
insert into patients (patient_id, google_email) values ('P01', 'example@gmail.com');
```

研究者による抽出：

```sql
select * from headache_events where patient_id = 'P01' order by onset_at;
select * from fitbit_sleep order by patient_id, date;   -- 全員分
```

撤回時：

```sql
update patients set status='withdrawn' where patient_id='P01';
-- データも削除する場合（全データが連鎖削除される）
delete from patients where patient_id='P01';
```

## 5. 開発・テスト

```bash
pip install -r requirements-dev.txt
python -m pytest tests -v
```

`tests/test_tenant_shim.py` は supabase クライアントをダミーに差し替えて動くため、ネットワーク不要。
