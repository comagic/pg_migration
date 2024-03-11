--parent_release: None

\set ON_ERROR_STOP on

begin;

\i ../extensions/plpgsql_check.sql
\i migration/migration.sql
\i migration/tables/release.sql

commit;
