-- 頭痛リスク可視化アプリ マルチテナント用スキーマ
-- 新しい Supabase プロジェクトの SQL Editor で実行する。

create table if not exists patients (
    patient_id   text primary key,
    google_email text not null unique check (google_email = lower(google_email)),
    display_name text,
    status       text not null default 'active' check (status in ('active','withdrawn')),
    enrolled_at  timestamptz not null default now()
);

create table if not exists fitbit_tokens (
    patient_id     text primary key references patients(patient_id) on delete cascade,
    access_token   text,
    refresh_token  text,
    expires_at     bigint,
    fitbit_user_id text
);

create table if not exists fitbit_sleep (
    patient_id   text not null references patients(patient_id) on delete cascade,
    date         text not null,
    sleep_start  text, sleep_end text,
    duration_min integer, efficiency integer,
    deep_min integer, light_min integer, rem_min integer, wake_min integer,
    primary key (patient_id, date)
);

create table if not exists fitbit_hrv (
    patient_id text not null references patients(patient_id) on delete cascade,
    date       text not null,
    rmssd numeric, resting_hr integer, coverage numeric,
    primary key (patient_id, date)
);

create table if not exists pressure_log (
    patient_id   text not null references patients(patient_id) on delete cascade,
    timestamp    text not null,
    pressure_hpa numeric, lat numeric, lon numeric,
    primary key (patient_id, timestamp)
);

create table if not exists settings (
    patient_id text not null references patients(patient_id) on delete cascade,
    key   text not null,
    value text,
    primary key (patient_id, key)
);

create table if not exists headache_events (
    id         bigint generated always as identity primary key,
    patient_id text not null references patients(patient_id) on delete cascade,
    onset_at text, end_at text, intensity integer, notes text
);
create index if not exists idx_headache_events_patient on headache_events(patient_id);

create table if not exists medications (
    id                bigint generated always as identity primary key,
    patient_id        text not null references patients(patient_id) on delete cascade,
    headache_event_id bigint references headache_events(id) on delete cascade,
    drug_name text, dose_amount numeric, dose_unit text, taken_at text
);
create index if not exists idx_medications_patient on medications(patient_id);

-- RLS: 全表で有効化し、ポリシーは作らない。
-- アプリはサーバー側から secret キー（RLSをバイパス）で接続するので動作する。
-- 公開用の publishable キーでは一切読み書きできない状態にする（患者データ保護）。
alter table patients        enable row level security;
alter table fitbit_tokens   enable row level security;
alter table fitbit_sleep    enable row level security;
alter table fitbit_hrv      enable row level security;
alter table pressure_log    enable row level security;
alter table settings        enable row level security;
alter table headache_events enable row level security;
alter table medications     enable row level security;
