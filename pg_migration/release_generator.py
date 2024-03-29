import os

import git

from .migration import Migration


class ChangedObject:
    types = [
        'schema',
        'type',
        'table',
        'function',
    ]

    def __init__(self, change_type, path, b_path):
        self.change_type = change_type
        self.path = path
        self.b_path = b_path
        self.type = self.get_type(path)
        self.name = self.get_name()

    @staticmethod
    def get_type(path):
        for type in ChangedObject.types:
            if ('/' + type + 's/') in path:
                return type
        return 'schema'  # FIXME

    def get_name(self):
        if self.type == 'schema':
            return os.path.basename(self.path)
        name = None
        path = self.path.split(os.sep)
        if len(path) == 4:
            name = f'{path[1]}.{path[3].split(".")[0]}'
            name = name.replace('public.', '')
        return name

    def get_migration_commands(self):
        if self.change_type == 'D':
            return [f'drop {self.type} {self.name};']
        if self.change_type == 'R':
            if self.type == 'function':
                return [
                    f'drop {self.type} {self.name};',
                    f'\\i {self.b_path.replace("schemas/", "")}'
                ]
        return [f'\\i {self.path.replace("schemas/", "")}']


class ReleaseGenerator:
    migration: Migration

    def __init__(self, args, migration):
        self.migration = migration
        self.args = args

    @staticmethod
    def get_staged_files():
        res = []
        repo = git.Repo()
        for df in repo.head.commit.diff(git.IndexFile.Index):
            if 'schemas/' in df.a_path:
                res.append(ChangedObject(df.change_type, df.a_path, df.b_path))
        return res

    def get_migration_commands(self):
        res = []
        objects = self.get_staged_files()
        for o in sorted(objects, key=lambda x: ChangedObject.types.index(x.type)):
            res.extend(o.get_migration_commands())
        return res

    def get_body(self):
        return '\n'.join([
            f'--parent_release: {self.migration.head}',
            '',
            '\\set ON_ERROR_STOP on',
            '',
            'begin;',
            '',
            '\n'.join(self.get_migration_commands()),
            '',
            'commit;',
            '',
        ])

    def generate_release(self):
        body = self.get_body()
        if self.args.migration == 'head':
            print(body)
        else:
            rel_dir = os.path.join('migrations', self.args.migration)
            os.makedirs(os.path.join('migrations', self.args.migration), exist_ok=True)
            open(os.path.join(rel_dir, 'release.sql'), 'a').write(body)
