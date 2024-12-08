import argparse
import asyncio
import os
import signal
import sys
from asyncio.subprocess import Process

from .migration import Migration
from .pg import Pg


class Upgrader:
    args: argparse.Namespace
    migration: Migration
    pg: Pg
    psql: Process
    cancel_task: asyncio.Task

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

        for release in ahead:
            version = release.version
            if version == current_version:
                continue
            command = f'psql "{self.args.dsn}" -f ../migrations/{version}/release.sql'
            print(command)
            self.psql = await asyncio.create_subprocess_shell(
                command,
                cwd='./schemas'
            )
            self.cancel_task = asyncio.create_task(self.cancel())
            await self.psql.wait()
            self.cancel_task.cancel()
            if self.psql.returncode != 0:
                exit(1)
            await self.pg.set_current_version(version)

    async def cancel(self):
        if self.args.timeout:
            await asyncio.sleep(self.args.timeout)
            print(f'cancel upgrade by timeout {self.args.timeout}s')
            self.psql.send_signal(signal.SIGINT)
