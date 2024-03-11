create table migration.release (
  version text not null,
  release_time timestamp with time zone not null default now()
);
