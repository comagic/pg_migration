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

    async def fetch(self, query, *params):
        return await self.connect.fetch(query, *params)

    async def get_current_version(self) -> str:
        res = await self.fetch('''
            select r.version
              from migration.release r
             order by r.release_time desc
             limit 1
        ''')
        if res:
            return res[0]['version']
