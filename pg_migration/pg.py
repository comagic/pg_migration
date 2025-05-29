import asyncpg
import argparse


class Pg:
    args: argparse.Namespace
    connect: asyncpg.Connection

    def __init__(self, args):
        self.args = args

    async def init_connection(self):
        self.connect = await asyncpg.connect(
            host=self.args.host,
            port=self.args.port,
            user=self.args.user,
            database=self.args.dbname,
            statement_cache_size=0
        )

    async def init_db(self):
        await self.execute('''
            create schema migration;
            create table migration.release(
              version text not null, 
              release_time timestamp with time zone not null default now()
            );
        ''')

    async def fetch(self, query, *params):
        return await self.connect.fetch(query, *params)

    async def execute(self, query, *params):
        return await self.connect.execute(query, *params)

    async def get_current_version(self) -> str:
        res = await self.fetch('''
            select r.version
              from migration.release r
             order by r.release_time desc
             limit 1
        ''')
        if res:
            return res[0]['version']

    async def add_release_version(self, version, section):
        table = self.get_release_table(section)
        await self.execute(f'''
            insert into {table}(version)
              values ($1)
        ''', version)

    async def plpgsql_check_functions(self):
        return await self.fetch('''
            select p.oid::regproc as func, 
                   pcf.error
              from pg_proc p
             inner join pg_language l
                     on l.oid = p.prolang
             cross join plpgsql_check_function(p.oid::regprocedure, 
                                               other_warnings := false, 
                                               extra_warnings := false) as pcf(error)
             where l.lanname = 'plpgsql' AND
                   p.prorettype <> 'trigger'::regtype and
                   p.pronamespace <> 'pg_catalog'::regnamespace
             order by 1;
        ''')

    async def plpgsql_check_triggers(self):
        return await self.fetch('''
            select pcf.functionid::regproc as func,
                   t.tgrelid::regclass as rel,
                   pcf.message as error
              from pg_proc p
             inner join pg_language l
                     on l.oid = p.prolang
             inner join pg_trigger t
                     on t.tgfoid = p.oid
             cross join plpgsql_check_function_tb(p.oid, t.tgrelid,
                                                  other_warnings := false,
                                                  extra_warnings := false) as pcf
             where l.lanname = 'plpgsql' and
                   p.prorettype = 'trigger'::regtype and
                   p.pronamespace <> 'pg_catalog'::regnamespace
             order by 1, 2;
        ''')

    async def cancel_blocking_backends(self, main_application_name):
        return await self.fetch(f'''
            select a.pid,
                   a.datname as database,
                   a.usename as user,
                   a.state,
                   clock_timestamp() - a.query_start as duration,
                   replace(substr(a.query, 1, 150), e'\n', '\n') as query,
                   case
                     when a.state = 'idle in transaction'
                       then pg_terminate_backend(a.pid)
                     else pg_cancel_backend(a.pid)
                   end as cancel_backend
              from pg_stat_activity da
             cross join pg_blocking_pids(da.pid) bp(blocking_pids)
             inner join pg_stat_activity a
                     on a.pid = any(bp.blocking_pids)
             where da.application_name = '{main_application_name}'
             order by duration desc;
        ''')

    async def get_release_time(self, version, section='release'):
        table = self.get_release_table(section)
        res = await self.fetch(
            f'''
            select release_time::timestamp(0)
              from {table}
             where version = $1
            ''',
            version
        )
        if res:
            return res[0]['release_time']

    @staticmethod
    def get_release_table(section):
        if section == 'release':
            return 'migration.release'
        elif section == 'pre-release':
            return 'migration.pre_release'
        elif section == 'post-release':
            return 'migration.post_release'
