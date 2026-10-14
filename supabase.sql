-- Reel cloud sync. Paste into Supabase > SQL Editor > Run.
-- Safe to run again any time — it only adds what's missing (accounts upgrade included).

create table if not exists reel_progress (
  id       text,                       -- what you watched: ep:<show>:<season>:<episode> / mv:<title>:<year>
  title    text,
  pos      double precision default 0, -- resume point (seconds)
  dur      double precision default 0,
  watched  boolean default false,
  t        double precision,           -- last change (unix time); newest wins
  device   text
);

create table if not exists reel_library (
  id       text primary key,           -- <device>:<path>
  device   text,
  kind     text,                       -- movie | episode | video
  title    text,
  year     int,
  season   int,
  episode  int,
  path     text,
  size     bigint,
  added    double precision,
  sync_id  text
);

-- Accounts: each person gets their own watch state + library, kept separate.
create table if not exists reel_accounts (
  id          text primary key,        -- slug of the name ('owner', 'brother', …)
  name        text,
  pin         text,                    -- soft lock (family trust), not real security
  role        text default 'member',   -- 'owner' | 'member'
  active      boolean default true,    -- owner can revoke → false locks that person out
  device      text,                    -- the device currently signed in
  now_playing text,                    -- what they're watching (for the owner's panel)
  last_seen   double precision,        -- heartbeat
  t           double precision
);

-- ---- accounts upgrade for existing installs: add the `account` column + per-account key ----
alter table reel_progress add column if not exists account text not null default 'owner';
alter table reel_library  add column if not exists account text not null default 'owner';

-- progress is now unique per (account, content) instead of just content
do $$ begin
  if exists (select 1 from pg_constraint where conname = 'reel_progress_pkey') then
    alter table reel_progress drop constraint reel_progress_pkey;
  end if;
  if not exists (select 1 from pg_constraint where conname = 'reel_progress_acct_pkey') then
    alter table reel_progress add constraint reel_progress_acct_pkey primary key (account, id);
  end if;
end $$;

-- Recommendations people send each other ("watch this"). Just a pointer, never the video.
create table if not exists reel_shares (
  id           text primary key,     -- <to>|<from>|<title-key>
  to_account   text,
  from_account text,
  from_name    text,
  kind         text,                 -- movie | series
  meta_id      text,                 -- cinemeta id if known
  name         text,
  year         text,
  poster       text,
  background   text,
  note         text,
  status       text default 'sent',  -- sent | dismissed
  t            double precision
);

-- Personal project: the app talks to these tables with your publishable/anon key.
alter table reel_progress enable row level security;
alter table reel_library  enable row level security;
alter table reel_accounts enable row level security;
alter table reel_shares   enable row level security;
drop policy if exists "reel anon" on reel_progress;
drop policy if exists "reel anon" on reel_library;
drop policy if exists "reel anon" on reel_accounts;
drop policy if exists "reel anon" on reel_shares;
create policy "reel anon" on reel_progress for all to anon using (true) with check (true);
create policy "reel anon" on reel_library  for all to anon using (true) with check (true);
create policy "reel anon" on reel_accounts for all to anon using (true) with check (true);
create policy "reel anon" on reel_shares   for all to anon using (true) with check (true);
