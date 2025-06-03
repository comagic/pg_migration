import argparse
import asyncio
import os
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
        print(f'error: {message}', file=sys.stderr)
        exit(1)

    def log(self, message, file=sys.stdout):
        print(message, file=file)

    async def upgrade(self):
        self.migration.check_multi_head()
        current_version = await self.pg.get_current_version()
        ahead = self.migration.get_ahead(current_version, self.args.version)
        if not ahead:
            self.error('cannot determine ahead')
        if len(ahead) > 2:
            missed_release = Migration.str_versions(ahead[1:-1])
            if self.args.no_chain:
                self.error(f'--no-chain: missed releases: {missed_release}, '
                           f'you need upgrade to missed releases before or do not use --no-chain')
            if self.args.section != 'all':
                self.error(f'missed releases: {missed_release}, '
                           f'cannot upgrade releases chain with --section: {self.args.section} (only all)')
        version = self.args.version or self.migration.head.version
        if self.args.section == 'pre-release':
            await self.upgrade_section(version, 'pre-release')
        elif self.args.section == 'release':
            await self.upgrade_section(version, 'release')
        elif self.args.section == 'post-release':
            await self.upgrade_section(version, 'post-release')
        elif self.args.section == 'all':
            if len(ahead) == 1:
                self.log('database is up to date')
                exit(0)
            for release in ahead:
                version = release.version
                if version == current_version:
                    continue
                await self.upgrade_section(version, 'pre-release')
                await self.upgrade_section(version, 'release')
                await self.upgrade_section(version, 'post-release')

    async def upgrade_section(self, version, section):
        release_time = await self.pg.get_release_time(version, section)
        file = self.get_release_file(section)
        if release_time:
            self.log(f'migration {version}/{file} already released "{release_time}", skip')
            return
        file_path = os.path.join('migrations', version, file)
        if not os.path.exists(file_path) and section in ('pre-release', 'post-release'):
            self.log(f'file not exists: {file_path}, skip')
            return
        command = f'psql "{self.args.dsn}" -c "{self.set_application_name}" -f ../{file_path}'
        self.log(command)
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
        await self.pg.add_release_version(version, section)

    @staticmethod
    def get_release_file(section):
        if section == 'release':
            return 'release.sql'
        elif section == 'pre-release':
            return 'pre-release.sql'
        elif section == 'post-release':
            return 'post-release.sql'

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
