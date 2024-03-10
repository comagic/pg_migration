# pg-migration

## instalation
pip install pg-migration

## usage
```
$ pg_migration --help
usage: pg_migration [--help] [-d DBNAME] [-h HOST] [-p PORT] [-U USER] [-W PASSWORD] command [migration]

Migration control system

positional arguments:
  command               { diff | upgrade | generate | log | plpgsql_check }
  migration             migration filename

options:
  --help                show this help message and exit
  -d DBNAME, --dbname DBNAME
                        database name to connect to
  -h HOST, --host HOST  database server host or socket directory
  -p PORT, --port PORT  database server port
  -U USER, --user USER  database user name
  -W PASSWORD, --password PASSWORD
                        database user password

Report bugs to <a.n.d@inbox.ru>.
```
