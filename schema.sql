-- Supabase (PostgreSQL) schema for the NC radar pipeline — multi-source version.
-- One row per (source, 5-min slot). source is 'NC-MOSAIC', 'NOUMEA' or 'LIFOU'.

create table if not exists public.radar_frames (
    id           bigserial primary key,
    source       text not null,                 -- 'NC-MOSAIC' | 'NOUMEA' | 'LIFOU'
    name         text,                          -- human label
    product      text not null default 'REFLECTIVITE',
    observed_at  timestamptz not null,          -- nominal time, UTC, 5-min slots
    image_path   text not null,                 -- path inside the Storage bucket
    bbox         jsonb not null,                -- {south,north,west,east} overlay bounds
    nx           int,
    ny           int,
    echo_pixels  int,
    created_at   timestamptz not null default now(),
    unique (source, observed_at)                -- dedup per source per slot
);

create index if not exists radar_frames_recent_idx
    on public.radar_frames (source, observed_at desc);

-- If you already created the earlier single-source table, migrate instead:
--   alter table public.radar_frames add column if not exists source text;
--   alter table public.radar_frames add column if not exists name text;
--   update public.radar_frames set source = 'NC-MOSAIC' where source is null;
--   alter table public.radar_frames drop constraint if exists radar_frames_zone_product_observed_at_key;
--   alter table public.radar_frames add constraint radar_frames_source_obs_key unique (source, observed_at);

-- Storage bucket 'radar' (public if the widget reads PNGs by URL).
-- Retention (pg_cron):  delete from public.radar_frames
--                       where observed_at < now() - interval '48 hours';
