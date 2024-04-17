import argparse
import os

from .migration import Migration
from .pg import Pg


class Upgrader:
    args: argparse.Namespace
    migration: Migration
    pg: Pg

    def __init__(self, args, migration, pg):
        self.args = args
        self.migration = migration
        self.pg = pg

    async def upgrade(self):
        current_version = await self.pg.get_current_version()
        if self.args.version == 'head':
            to_version = self.migration.head
        else:
            to_version = self.args.version
        if current_version == to_version:
            print('database is up to date')
            exit(0)

        ahead = self.migration.get_ahead(current_version, self.args.version)
        if not ahead:
            print('cannot determine ahead')
            exit(1)

        os.chdir('./schemas')
        for version in ahead:
            print(f'psql "{self.args.dsn}" -f ../migrations/{version}/release.sql')
            code = os.system(f'psql "{self.args.dsn}" -f ../migrations/{version}/release.sql') >> 8
            if code != 0:
                exit(code)
            await self.pg.set_current_version(version)
        os.chdir('..')
