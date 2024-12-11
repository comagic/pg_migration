import asyncio
import os
import re
import signal
import sys
from asyncio.subprocess import Process

from .migration import Migration
from .pg import Pg


class Dsn:
    dsn_pattern = '(.*@)?([^@:]+):(\\d+)/(.+)'

    def __init__(self, dsn):
        self.dsn = dsn
        self.user, self.host, self.port, self.dbname = re.match(self.dsn_pattern, dsn).groups()
        if self.user:
            self.user = self.user[:-1]  # del "@"
        self.port = int(self.port)


class DistributeUpgrader:
    READY = 'ready'
    DONE = 'done'
    ERROR = 'error'
    ready_cmd = '\n\\echo READY TO COMMIT\n'
    migration: Migration
    pg: Pg
    psql: Process
    before_commit_commands: str
    commit_command: str
    is_up_to_date: bool
    cancel_task: asyncio.Task
    stderr_reader_task: asyncio.Task
    current_version: str

    def __init__(self, dsn: str, migration_path: str, timeout: int):
        self.dsn = Dsn(dsn)
        self.migration_path = os.path.normpath(migration_path)
        self.timeout = timeout
        root_dir = self.migration_path.split(os.sep)[:-2]
        if root_dir:
            self.root_dir = os.path.join(*root_dir)
        else:
            self.root_dir = './'
        if self.root_dir == './':
            self.relative_migration_path = self.migration_path
        else:
            self.relative_migration_path = f'{self.migration_path[len(self.root_dir) + 1:]}'
        self.pg = Pg(self.dsn)
        self.migration = Migration(None, self.pg, os.path.join(self.root_dir, 'migrations'))
        self.version = self.migration_path.split(os.sep)[-1]
        self.get_release_body()
        self.is_up_to_date = False

    def error(self, message):
        print(f'{self.dsn.dbname}: ERROR: {message}', file=sys.stderr)
        exit(1)

    def log(self, message):
        print(f'{self.dsn.dbname}: {message}')

    def get_release_body(self):
        file_name = os.path.join(self.migration_path, 'release.sql')
        body = open(file_name).read()
        if '\ncommit;' not in body:
            self.error(f'cannot find "commit;" in {file_name}')
        self.before_commit_commands, self.commit_command = body.split('\ncommit;')
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

    def check_ahead(self):
        ahead = self.migration.get_ahead(self.current_version, self.version)
        if not ahead:
            self.error('Cannot determine ahead')

        if len(ahead) != 2:
            chain = ', '.join(release.version for release in ahead[1:])
            self.error(f'Cannot update several versions ahead at once in distribute mode: {chain}')

    async def run_before_commit(self):
        await self.pg.init_connection()
        self.current_version = await self.pg.get_current_version()
        if self.current_version == self.version:
            self.log('database is up to date')
            self.is_up_to_date = True
            return self.READY

        self.check_ahead()

        psql_work_dir = os.path.join(self.root_dir, 'schemas')
        command = f'psql "postgresql://{self.dsn.dsn}"'
        self.log(f'cd {psql_work_dir}; {command} -f ../{self.relative_migration_path}/release.sql')
        self.psql = await asyncio.create_subprocess_shell(
            command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=psql_work_dir
        )
        self.cancel_task = asyncio.create_task(self.cancel())
        self.stderr_reader_task = asyncio.create_task(self.stderr_reader())
        self.psql.stdin.write(self.before_commit_commands.encode('utf8'))
        res = await self.wait_psql(ready_string='READY TO COMMIT')
        self.cancel_task.cancel()
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
        await self.pg.set_current_version(self.version)
        return self.DONE

    async def rollback(self):
        self.commit_command = 'rollback'
        await self.commit()

    async def cancel(self):
        if self.timeout:
            await asyncio.sleep(self.timeout)
            self.log(f'cancel upgrade by timeout {self.timeout}s')
            self.psql.send_signal(signal.SIGINT)
