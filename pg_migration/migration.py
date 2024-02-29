import argparse
import os
import re

from .pg import Pg


class Migration:
    args: argparse.Namespace
    pg: Pg
    chain: dict

    def __init__(self, args, pg):
        self.args = args
        self.pg = pg
        self.chain = {}
        self.parse('migrations')

    @staticmethod
    def get_parent_release(file_name, header):
        res = re.match('parent_release: (.*)', header)
        if not res:
            raise Exception(f'"parent_release" not found in {file_name}')
        res = res.groups()[0]
        if res == 'None':
            return None
        return res

    def parse(self, root):
        for release in os.listdir(root):
            file_name = os.path.join(root, release, 'release.sql')
            header = open(file_name).readline()
            parent = self.get_parent_release(file_name, header)
            self.chain[parent] = release

    def get_ahead(self, from_version, to_version):
        versions = []
        version = from_version
        while True:
            version = self.chain.get(version)
            if not version:
                break
            versions.append(version)
            if version == to_version:
                break
        return versions

    async def print_diff(self):
        version = await self.pg.get_current_version()
        print(f'{version}*')
        for version in self.get_ahead(version, self.args.migration):
            print(version)

    async def print_log(self):
        from_version = None
        to_version = None
        if ':' in self.args.migration:
            from_version, to_version = self.args.migration.split(':')
        if from_version:
            print(f'{from_version}')
        for version in self.get_ahead(from_version, to_version):
            print(version)
