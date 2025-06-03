import argparse
import asyncio
import os
import re
import sys

from .migration import Migration
from .pg import Pg
from .upgrader import Upgrader


class Dsn:
    dsn_pattern = '(.*@)?([^@:]+):(\\d+)/(.+)'

    def __init__(self, dsn):
        self.dsn = f"postgresql://{dsn}"
        self.user, self.host, self.port, self.dbname = re.match(self.dsn_pattern, dsn).groups()
        if self.user:
            self.user = self.user[:-1]  # del "@"
        self.port = int(self.port)


class DistributeUpgrader(Upgrader):
    READY = 'ready'
    DONE = 'done'
    ERROR = 'error'
    ready_cmd = '\n\\echo READY TO COMMIT\n'
    before_commit_commands: str
    commit_command: str
    is_up_to_date: bool
    stderr_reader_task: asyncio.Task

    def __init__(self, args: argparse.Namespace, dsn: str, migration_path: str, chain_migrations_path: str):
        self.dsn = Dsn(dsn)
        self.migration_path = os.path.normpath(migration_path)
        self.version = self.migration_path.split(os.sep)[-1]
        root_dir = self.migration_path.split(os.sep)[:-2]
        self.root_dir = os.path.join(*root_dir) if root_dir else '.'
        pg = Pg(self.dsn)
        migration_root_path = chain_migrations_path or os.path.join(self.root_dir, 'migrations')
        migration = Migration(None, pg, migration_root_path)
        super().__init__(args, migration, pg)
        self.psql_work_dir = os.path.join(self.root_dir, 'schemas')
        file = self.get_release_file(self.args.section)
        if self.root_dir == '.':
            self.relative_migration_path = self.migration_path
        else:
            self.relative_migration_path = f'{self.migration_path[len(self.root_dir) + 1:]}'
        self.relative_file_path = os.path.join(self.relative_migration_path, file)
        self.file_path = os.path.join(self.migration_path, file)
        self.is_up_to_date = False

    def error(self, message):
        print(f'{self.dsn.dbname}: ERROR: {message}', file=sys.stderr)
        exit(1)

    def log(self, message, file=sys.stdout):
        print(f'{self.dsn.dbname}: {message}', file=file)

    def get_release_body(self):
        file_name = os.path.join(self.migration_path, 'release.sql')
        body = open(file_name).read()
        if '\ncommit;' not in body:
            self.error(f'cannot find "commit;" in {file_name}')
        self.before_commit_commands, self.commit_command = body.split('\ncommit;')
        self.before_commit_commands = f'{self.set_application_name}\n{self.before_commit_commands}'
        self.before_commit_commands += self.ready_cmd
        self.commit_command = 'commit;\n' + self.commit_command
        self.before_commit_commands = self.before_commit_commands.replace(
            '\\ir ',
            f'\\i ../{self.relative_migration_path}/'
        )

    async def stderr_reader(self):
        while True:
            message = await self.psql.stderr.readline()
            message = message.decode()
            if message == '':
                break
            self.log(f'STDERR: {message.rstrip()}')

    async def wait_psql(self, ready_string=None):
        while True:
            message = await self.psql.stdout.readline()
            message = message.decode()
            if message == '':
                return
            self.log(message.rstrip())
            if ready_string and ready_string in message:
                return self.READY

    async def check_ahead(self):
        current_version = await self.pg.get_current_version()
        ahead = self.migration.get_ahead(current_version, self.version)
        if not ahead:
            self.error('Cannot determine ahead')
        if len(ahead) != 2:
            chain = Migration.str_versions(ahead[1:])
            self.error(f'Cannot update several versions ahead at once in distribute mode: {chain}')

    async def run_before_commit(self):
        self.get_release_body()
        await self.pg.init_connection()
        if await self.check_already_released():
            self.is_up_to_date = True
            return self.READY
        await self.check_ahead()

        command = f'psql "{self.dsn.dsn}"'
        self.log(f'cd {self.psql_work_dir}; {command} -f ../{self.relative_migration_path}/release.sql')
        self.psql = await asyncio.create_subprocess_shell(
            command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.psql_work_dir
        )
        self.cancel_by_timeout_task = asyncio.create_task(self.cancel_by_timeout())
        self.cancel_blocking_backends_task = asyncio.create_task(self.cancel_blocking_backends())
        self.stderr_reader_task = asyncio.create_task(self.stderr_reader())
        self.psql.stdin.write(self.before_commit_commands.encode('utf8'))
        res = await self.wait_psql(ready_string='READY TO COMMIT')
        self.cancel_by_timeout_task.cancel()
        self.cancel_blocking_backends_task.cancel()
        return res

    async def commit(self):
        if self.is_up_to_date:
            return self.DONE
        if self.psql.returncode is None:
            self.psql.stdin.write(self.commit_command.encode('utf8'))
            self.psql.stdin.close()
            await self.wait_psql()
        await self.psql.wait()
        await self.stderr_reader_task
        if self.psql.returncode != 0:
            self.log(f'psql exited with error code: {self.psql.returncode}')
            return self.ERROR
        if self.commit_command == 'rollback':
            return self.ERROR
        await self.pg.add_release_version(self.version, 'release')
        return self.DONE

    async def rollback(self):
        self.commit_command = 'rollback'
        await self.commit()

    async def upgrade(self):
        await self.pg.init_connection()
        self.migration.check_multi_head()
        if await self.check_already_released():
            return self.DONE
        if not os.path.exists(self.file_path) and self.args.section in ('pre-release', 'post-release'):
            self.log(f'file not exists: {self.file_path}, skip')
            return self.DONE

        command = f'psql "{self.dsn.dsn}" -c "{self.set_application_name}" -f ../{self.relative_file_path}'
        self.log(f'cd {self.psql_work_dir}; {command}')
        self.psql = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.psql_work_dir
        )
        self.cancel_by_timeout_task = asyncio.create_task(self.cancel_by_timeout())
        self.cancel_blocking_backends_task = asyncio.create_task(self.cancel_blocking_backends())
        self.stderr_reader_task = asyncio.create_task(self.stderr_reader())
        await self.wait_psql()
        await self.psql.wait()
        self.cancel_by_timeout_task.cancel()
        self.cancel_blocking_backends_task.cancel()
        if self.psql.returncode != 0:
            return self.ERROR
        await self.pg.add_release_version(self.version, self.args.section)
        return self.DONE

    async def check_already_released(self):
        release_time = await self.pg.get_release_time(self.version, self.args.section)
        if release_time:
            self.log(f'migration {self.file_path} already released "{release_time}", skip')
            return True
