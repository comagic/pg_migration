import sys
from argparse import Namespace
import os
import re
from typing import Optional, Dict, List

from .pg import Pg


Version = str
AUTO_PARENT = 'auto'


class Release:
    version: str
    parent_version: str
    parent: 'Release'
    children: list

    def __init__(self, version, parent_version, is_deleted=False):
        self.version = version
        self.parent_version = parent_version
        self.is_deleted = is_deleted
        self.children = []

    def __str__(self):
        deleted = ', deleted: True' if self.is_deleted else ''
        return f'version: {self.version}{deleted}, parent: {self.parent_version}'

    def __repr__(self):
        return f'<Release ({str(self)})>'


class Migration:
    args: Namespace
    pg: Pg
    chain: dict
    releases: Dict[Version, Release]
    tail: Optional[Release]
    tails: List[Release]
    head: Optional[Release]
    heads: List[Release]

    def __init__(self, args, pg=None, root='migrations'):
        self.args = args
        self.pg = pg
        self.chain = {}
        self.releases = {}
        self.tail = None
        self.tails = []
        self.head = None
        self.heads = []
        self.parse(root)

    @staticmethod
    def error(message):
        print(f'ERROR: {message}', file=sys.stderr)
        exit(1)

    def get_parent_version(self, file_name, header):
        res = re.match('--parent_release: (.*)', header)
        if not res:
            self.error(f'string "--parent_release: <version>" not found in {file_name}')
        res = res.groups()[0]
        if res == 'None':
            return None
        return res

    def parse(self, root):
        for version in os.listdir(root):
            file_name = os.path.join(root, version, 'release.sql')
            header = open(file_name).readline()
            parent_version = self.get_parent_version(file_name, header)
            self.releases[version] = Release(version, parent_version)

        auto_parent_releases = []
        for release in list(self.releases.values()):
            if release.parent_version:
                if release.parent_version == AUTO_PARENT:
                    auto_parent_releases.append(release)
                else:
                    if release.parent_version not in self.releases:
                        self.releases[release.parent_version] = Release(release.parent_version, None, True)
                    parent = self.releases[release.parent_version]
                    release.parent = parent
                    parent.children.append(release)

        if len(auto_parent_releases) > 1:
            self.error(f'only one release with "--parent_release: {AUTO_PARENT}" is allowed, '
                       f'but multiple found: {self.str_versions(auto_parent_releases)}')

        self.tails = [
            release
            for release in self.releases.values()
            if release.parent_version is None
        ]
        if len(self.tails) == 1:
            self.tail = self.tails[0]

        self.heads = [
            release
            for release in self.releases.values()
            if not release.children and release.parent_version != AUTO_PARENT
        ]
        if len(self.heads) == 1:
            self.head = self.heads[0]

        if auto_parent_releases:
            auto_parent_release = auto_parent_releases[0]
            if len(self.heads) != 1:
                self.error(f'Cannot determine best candidate for release "{auto_parent_release.version}" '
                           f'with "--parent_release: {AUTO_PARENT}", because multiple heads found: '
                           f'{self.str_versions(self.heads)}')
            auto_parent_release.parent = self.head
            self.head.children.append(auto_parent_release)
            self.head = auto_parent_release

    def get_ahead(self, from_version: Version, to_version: Version) -> List[Release]:
        ahead = []
        version = from_version
        if version not in self.releases:
            self.error(f'version {version} not found in migrations/')
        release = self.releases[version]
        ahead.append(release)
        while release.children:
            if len(release.children) > 1:
                self.error(f'parent {release.version} specified more than once, '
                           f'use "pg_migration log" for details')
                exit(1)
            release = release.children[0]
            ahead.append(release)
            if release.version == to_version:
                break
        return ahead

    async def print_diff(self) -> None:
        self.check_multi_head()
        db_version = await self.pg.get_current_version()
        if db_version and db_version not in self.releases:
            self.error(f'database version {db_version} not found in migrations/')
        for release in self.get_ahead(db_version, self.args.version):
            db_version_marker = ' (db)' if release.version == db_version else ''
            print(f'{release.version}{db_version_marker}')

    def print_log(self) -> None:
        start_version = None
        stop_version = None
        if self.args.version:
            start_version, stop_version = self.args.version.split(':')
        if start_version and start_version not in self.releases:
            self.error(f'start_version {start_version} not found')
        if stop_version and stop_version not in self.releases:
            self.error(f'stop_version {stop_version} not found')

        if start_version or stop_version:
            if len(self.tails) > 1:
                tails_versions = ", ".join(release.version for release in self.tails)
                self.error(f'several unrelated branches found: "{tails_versions}", use "pg_migration log" '
                           f'(without versions) for details')

        if start_version:
            self.print_branch(self.releases[start_version], stop_version)
            return

        for tail in self.tails:
            self.print_branch(tail, stop_version)
            if len(self.tails) > 1:
                print()

        if len(self.tails) > 1:
            self.error('several unrelated branches found')

        if self.args.no_multi_heads:
            self.check_multi_head()

    def print_branch(self, release, stop_version, level=0):
        tree = '| ' * level
        while True:
            deleted = ' (deleted)' if release.is_deleted else ''
            print(f'{tree}{release.version}{deleted}')
            if not release.children or release.version == stop_version:
                break
            elif len(release.children) == 1:
                release = release.children[0]
            elif len(release.children) > 1:
                if stop_version:
                    self.error(f'parent {release.version} specified more than once, use "pg_migration log" '
                               f'(without versions) for details')
                slashes = '\\ ' * (len(release.children) - 1)
                print(f'{tree}|{slashes}')
                for i in reversed(range(1, len(release.children))):
                    self.print_branch(release.children[i], stop_version, level+i)
                release = release.children[0]

    def check_multi_head(self):
        if len(self.heads) > 1:
            self.error(f'multi head detected: {self.str_versions(self.heads)}')

    @staticmethod
    def str_versions(releases):
        return ', '.join(
            release.version
            for release in releases
        )
