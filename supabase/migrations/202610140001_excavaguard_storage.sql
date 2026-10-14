begin;

create table if not exists public.excavaguard_projects (
  id uuid primary key,
  name text not null check (char_length(btrim(name)) between 1 and 200),
  created_at timestamptz not null default now()
);

create table if not exists public.excavaguard_project_members (
  project_id uuid not null references public.excavaguard_projects(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null check (role in ('owner', 'engineer', 'viewer')),
  created_at timestamptz not null default now(),
  primary key (project_id, user_id)
);

create table if not exists public.excavaguard_files (
  file_id uuid primary key,
  project_id uuid not null references public.excavaguard_projects(id) on delete cascade,
  kind text not null check (kind in ('monitoring', 'standard')),
  original_name text not null check (char_length(btrim(original_name)) between 1 and 500),
  storage_path text not null unique,
  size_bytes bigint not null check (size_bytes > 0 and size_bytes <= 20971520),
  media_type text not null,
  sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  created_at timestamptz not null default now()
);

create index if not exists excavaguard_files_project_created_idx
  on public.excavaguard_files (project_id, created_at desc);

create table if not exists public.excavaguard_run_revisions (
  run_id uuid not null,
  revision integer not null check (revision > 0),
  project_id uuid not null references public.excavaguard_projects(id) on delete cascade,
  record jsonb not null,
  created_at timestamptz not null default now(),
  primary key (run_id, revision)
);

create index if not exists excavaguard_run_revisions_project_created_idx
  on public.excavaguard_run_revisions (project_id, created_at desc);

create table if not exists public.excavaguard_report_artifacts (
  artifact_id uuid primary key,
  draft_id uuid not null,
  run_id uuid not null,
  project_id uuid not null references public.excavaguard_projects(id) on delete cascade,
  kind text not null check (kind in ('workbook', 'cover_markdown', 'appendices_markdown')),
  file_name text not null check (
    char_length(btrim(file_name)) between 1 and 500
    and file_name !~ '[/\\]'
  ),
  storage_path text not null unique,
  media_type text not null,
  sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  size_bytes bigint not null check (size_bytes > 0),
  created_at timestamptz not null default now(),
  unique (draft_id, kind)
);

create index if not exists excavaguard_report_artifacts_run_idx
  on public.excavaguard_report_artifacts (run_id, created_at desc);

create or replace function public.excavaguard_has_project_access(target_project_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.excavaguard_project_members
    where project_id = target_project_id
      and user_id = auth.uid()
  );
$$;

revoke all on function public.excavaguard_has_project_access(uuid) from public;
grant execute on function public.excavaguard_has_project_access(uuid) to authenticated;

alter table public.excavaguard_projects enable row level security;
alter table public.excavaguard_project_members enable row level security;
alter table public.excavaguard_files enable row level security;
alter table public.excavaguard_run_revisions enable row level security;
alter table public.excavaguard_report_artifacts enable row level security;

drop policy if exists "project members read projects" on public.excavaguard_projects;
create policy "project members read projects"
  on public.excavaguard_projects for select
  to authenticated
  using (public.excavaguard_has_project_access(id));

drop policy if exists "project members read memberships" on public.excavaguard_project_members;
create policy "project members read memberships"
  on public.excavaguard_project_members for select
  to authenticated
  using (public.excavaguard_has_project_access(project_id));

drop policy if exists "project members read files" on public.excavaguard_files;
create policy "project members read files"
  on public.excavaguard_files for select
  to authenticated
  using (public.excavaguard_has_project_access(project_id));

drop policy if exists "project members read run revisions" on public.excavaguard_run_revisions;
create policy "project members read run revisions"
  on public.excavaguard_run_revisions for select
  to authenticated
  using (public.excavaguard_has_project_access(project_id));

drop policy if exists "project members read report artifacts" on public.excavaguard_report_artifacts;
create policy "project members read report artifacts"
  on public.excavaguard_report_artifacts for select
  to authenticated
  using (public.excavaguard_has_project_access(project_id));

revoke all on table
  public.excavaguard_projects,
  public.excavaguard_project_members,
  public.excavaguard_files,
  public.excavaguard_run_revisions,
  public.excavaguard_report_artifacts
from anon;

revoke insert, update, delete on table
  public.excavaguard_projects,
  public.excavaguard_project_members,
  public.excavaguard_files,
  public.excavaguard_run_revisions,
  public.excavaguard_report_artifacts
from authenticated;

grant select on table
  public.excavaguard_projects,
  public.excavaguard_project_members,
  public.excavaguard_files,
  public.excavaguard_run_revisions,
  public.excavaguard_report_artifacts
to authenticated;

grant all on table
  public.excavaguard_projects,
  public.excavaguard_project_members,
  public.excavaguard_files,
  public.excavaguard_run_revisions,
  public.excavaguard_report_artifacts
to service_role;

insert into storage.buckets (
  id,
  name,
  public,
  file_size_limit,
  allowed_mime_types
)
values (
  'excavaguard-private',
  'excavaguard-private',
  false,
  20971520,
  array[
    'text/csv',
    'text/tab-separated-values',
    'text/plain',
    'application/json',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.ms-excel.sheet.macroEnabled.12',
    'text/markdown',
    'application/octet-stream'
  ]
)
on conflict (id) do update set
  public = false,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

-- No storage.objects policy is created. Browser clients cannot read or write
-- objects directly; the secured server API remains the only object gateway.

commit;
