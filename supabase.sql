-- Reel cloud sync. Paste into Supabase > SQL Editor > Run (once).

create table if not exists reel_progress (
  id       text primary key,          -- what you watched: ep:<show>:<season>:<episode> / mv:<title>:<year>
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

-- Personal project: the app talks to these tables with your anon key.
alter table reel_progress enable row level security;
alter table reel_library  enable row level security;
drop policy if exists "reel anon" on reel_progress;
drop policy if exists "reel anon" on reel_library;
create policy "reel anon" on reel_progress for all to anon using (true) with check (true);
create policy "reel anon" on reel_library  for all to anon using (true) with check (true);
