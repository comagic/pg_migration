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

    async def set_current_version(self, version):
        await self.execute('''
            insert into migration.release(version)
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
                   p.pronamespace <> 'pg_catalog'::regnamespace and
                   pcf.functionid::regproc::text <> 'utils.biu_check_query'
             order by 1, 2;
        ''')
