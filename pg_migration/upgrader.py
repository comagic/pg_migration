import argparse
import asyncio
import signal
import sys
from asyncio.subprocess import Process
from typing import Union

from .migration import Migration
from .pg import Pg


class Upgrader:
    args: argparse.Namespace
    migration: Migration
    pg: Pg
    psql: Union[Process, None]
    cancel_by_timeout_task: asyncio.Task
    cancel_blocking_backends_task: asyncio.Task
    cancel_blocking_backends_timeout = 2
    application_name = 'pg_migration_deploy'
    set_application_name = f"set application_name = '{application_name}';"

    def __init__(self, args, migration, pg):
        self.args = args
        self.migration = migration
        self.pg = pg
        self.psql = None

    def error(self, message):
        print(message, file=sys.stderr)
        exit(1)

    def log(self, message, file=sys.stdout):
        print(message, file=file)

    async def upgrade(self):
        self.migration.check_multi_head()
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
            command = f'psql "{self.args.dsn}" -c "{self.set_application_name}" -f ../migrations/{version}/release.sql'
            print(command)
            self.psql = await asyncio.create_subprocess_shell(
                command,
                cwd='./schemas'
            )
            self.cancel_by_timeout_task = asyncio.create_task(self.cancel_by_timeout())
            self.cancel_blocking_backends_task = asyncio.create_task(self.cancel_blocking_backends())
            await self.psql.wait()
            self.cancel_by_timeout_task.cancel()
            self.cancel_blocking_backends_task.cancel()
            if self.psql.returncode != 0:
                exit(1)
            await self.pg.set_current_version(version)

    async def cancel_by_timeout(self):
        if self.args.timeout:
            await asyncio.sleep(self.args.timeout)
            self.log(f'cancel upgrade by timeout {self.args.timeout}s')
            self.cancel()

    def cancel(self):
        if self.psql and self.psql.returncode is None:
            self.log('send SIGINT to psql')
            self.psql.send_signal(signal.SIGINT)

    async def cancel_blocking_backends(self):
        if self.args.force:
            try:
                while True:
                    await asyncio.sleep(self.cancel_blocking_backends_timeout)
                    res = await self.pg.cancel_blocking_backends(self.application_name)
                    if res:
                        canceled_queries = '\n'.join(
                            f"  pid: {row['pid']}, "
                            f"database: {row['database']}, "
                            f"user: {row['user']}, "
                            f"state: {row['state']}, "
                            f"query_duration: {row['duration']}, "
                            f"query: {row['query']}"
                            for row in res
                        )
                        self.log(f'canceled queries (--force):\n{canceled_queries}')
            except Exception as e:
                self.log(f'error on canceling blocking backends: {e.__class__.__name__}: {e}', file=sys.stderr)
