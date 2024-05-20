import argparse
import os
import sys

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

    @staticmethod
    def error(message):
        print(message, file=sys.stderr)
        exit(1)

    async def upgrade(self):
        current_version = await self.pg.get_current_version()
        if self.args.version is None:
            to_version = self.migration.head.version
        else:
            to_version = self.args.version
        if current_version == to_version:
            print('database is up to date')
            exit(0)

        ahead = self.migration.get_ahead(current_version, self.args.version)
        if not ahead:
            self.error('cannot determine ahead')

        os.chdir('./schemas')
        for release in ahead:
            version = release.version
            if version == current_version:
                continue
            print(f'psql "{self.args.dsn}" -f ../migrations/{version}/release.sql')
            code = os.system(f'psql "{self.args.dsn}" -f ../migrations/{version}/release.sql') >> 8
            if code != 0:
                os.chdir('..')
                exit(code)
            await self.pg.set_current_version(version)
        os.chdir('..')
