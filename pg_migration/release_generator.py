import git

from .migration import Migration


class ChangedObject:
    types = [
        'schema',
        'type',
        'table',
        'function',
    ]

    def __init__(self, change_type, path):
        self.change_type = change_type
        self.path = path
        self.type = self.get_type(path)

    @staticmethod
    def get_type(path):
        for type in ChangedObject.types:
            if ('/' + type + 's/') in path:
                return type
        return 'schema'  # FIXME

    def get_migration_commands(self):
        return [f'\\i {self.path}']


class ReleaseGenerator:
    migration: Migration

    def __init__(self, args, migration):
        self.migration = migration
        self.args = args

    def get_staged_files(self):
        res = []
        repo = git.Repo()
        for df in repo.head.commit.diff(git.IndexFile.Index):
            if 'schemas/' in df.a_path:
                res.append(ChangedObject(df.change_type, df.a_path))
        return res

    def get_migration_commands(self):
        res = []
        objects = self.get_staged_files()
        for o in sorted(objects, key=lambda x:ChangedObject.types.index(x.type)):
            res.extend(o.get_migration_commands())
        return res

    def generate_release(self):
        print(f'--parent_release: {self.migration.head}')
        print('\nbegin;\n')
        print('\n'.join(self.get_migration_commands()))
        print('\ncommit;')
        print()
