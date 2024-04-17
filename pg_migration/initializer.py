import argparse
import os
import shutil


class Initializer:
    args: argparse.Namespace

    def __init__(self, args):
        self.args = args

    def initialize(self):
        template_dir = os.path.join(os.path.dirname(__file__), 'templates')
        os.makedirs('schemas/migration/tables/', exist_ok=True)
        shutil.copy(os.path.join(template_dir, 'migration.sql'), 'schemas/migration/')
        shutil.copy(os.path.join(template_dir, 'release.sql'), 'schemas/migration/tables/')
        shutil.copy(os.path.join(template_dir, '.gitlab-ci.yml'), './')
        os.makedirs(os.path.join('migrations', self.args.version), exist_ok=True)
        shutil.copy(
            os.path.join(template_dir, '0.0.sql'),
            os.path.join('migrations', self.args.version, 'release.sql')
        )
        os.makedirs('extensions', exist_ok=True)
        shutil.copy(os.path.join(template_dir, 'plpgsql_check.sql'), 'extensions/')
