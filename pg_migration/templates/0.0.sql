--parent_release: None

begin;

\i ../extensions/plpgsql_check.sql
\i migration/migration.sql
\i migration/tables/release.sql

commit;
