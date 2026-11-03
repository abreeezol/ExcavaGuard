begin;

-- Local account UUIDs do not reference auth.users. Identity is checked by the
-- server project ACL; this field only stores the authenticated uploader snapshot.
alter table public.excavaguard_files
  add column if not exists uploaded_by jsonb;

comment on column public.excavaguard_files.uploaded_by is
  'Authenticated uploader snapshot {id,name}; NULL means historical identity unavailable.';

commit;
