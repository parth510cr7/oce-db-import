-- Allow ON CONFLICT (checksum) for idempotent imports
do $$
begin
  if not exists (
    select 1
    from pg_indexes
    where schemaname = 'public'
      and indexname = 'sources_checksum_key'
  ) then
    alter table sources add constraint sources_checksum_key unique (checksum);
  end if;
end $$;

