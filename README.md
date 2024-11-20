## pg-migration - ci/cd automation

Migration control system for postgres database

## installation

```
pip install pg-migration
```

## usage

```
$ pg_migration --help
usage: pg_migration [-h] {log,diff,upgrade,generate,plpgsql_check,auto_merge,init} ...

optional arguments:
  -h, --help            show this help message and exit

commands:
  {log,diff,upgrade,generate,plpgsql_check,auto_merge,init}
    log                 print chain of migrations between from_version:to_version (or tail:head)
    diff                show difference between database and specified (or last) version
    upgrade             upgrade database up to specified (or last) version
    generate            generate migration file
    plpgsql_check       check functions and triggers with plpgsql_check extension
    auto_merge          creates merge-request when magic word "auto-commit" / "auto-deploy" is passed (uses in cd/cd)
    init                build migration which will create scheme migration and table migration.release

Report bugs: https://github.com/comagic/pg_migration/issues
```
