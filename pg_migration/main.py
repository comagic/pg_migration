import os
import argparse
import asyncio

from .gitlab import Gitlab
from .initializer import Initializer
from .migration import Migration
from .pg import Pg
from .plpgsql_checker import PlpgsqlChecker
from .release_generator import ReleaseGenerator
from .upgrader import Upgrader
from .distribute_upgrader import DistributeUpgrader
from . import __version__


node_format = 'migration_path -> [user@]host:port/database'


def build_dsn(args):
    parts = []
    if getattr(args, 'host', None):
        parts.append(f'host={args.host}')
    if getattr(args, 'port', None):
        parts.append(f'port={args.port}')
    if getattr(args, 'dbname', None):
        parts.append(f'dbname={args.dbname}')
    if getattr(args, 'user', None):
        parts.append(f'user={args.user}')
    if getattr(args, 'password', None):
        parts.append(f'password={args.password}')
    return ' '.join(parts)


def dir_path(value):
    if os.path.isdir(value):
        return value
    raise argparse.ArgumentTypeError(f"Cannot find directory: {value}")


async def run(args):
    if args.command == 'diff':
        pg = Pg(args)
        await pg.init_connection()
        await Migration(args, pg).print_diff()

    elif args.command == 'log':
        Migration(args).print_log()

    elif args.command == 'generate':
        migration = Migration(args)
        ReleaseGenerator(args, migration).generate_release()

    elif args.command == 'upgrade':
        if not args.distribute:
            pg = Pg(args)
            await pg.init_connection()
            migration = Migration(args, pg)
            await Upgrader(args, migration, pg).upgrade()
        else:
            upgraders = []
            for node in args.node:
                if '->' not in node:
                    print(f'node "{node}" not match format "{node_format}"')
                    exit(1)
                migration_path, dsn = map(str.strip, node.split('->'))
                migration_path = os.path.expanduser(migration_path)
                upgraders.append(DistributeUpgrader(args, dsn, migration_path, args.chain_migrations_path))

            if args.section == 'release':
                success_count = 0
                for future in asyncio.as_completed([
                    upgrader.run_before_commit()
                    for upgrader in upgraders
                ]):
                    res = await future
                    if res == DistributeUpgrader.READY:
                        success_count += 1
                    else:
                        for upgrader in upgraders:
                            upgrader.cancel()

                if success_count == len(upgraders):
                    res = await asyncio.gather(*[
                        upgrader.commit()
                        for upgrader in upgraders
                    ])
                    if res.count(DistributeUpgrader.DONE) != len(upgraders):
                        exit(1)
                else:
                    await asyncio.gather(*[
                        upgrader.rollback()
                        for upgrader in upgraders
                    ])
                    exit(1)
            else:
                res = await asyncio.gather(*[
                    upgrader.upgrade()
                    for upgrader in upgraders
                ])
                if res.count(DistributeUpgrader.DONE) != len(upgraders):
                    exit(1)

    elif args.command == 'plpgsql_check':
        pg = Pg(args)
        await pg.init_connection()
        await PlpgsqlChecker(pg).check()

    elif args.command == 'init':
        Initializer(args).initialize()

    elif args.command == 'auto_merge':
        await Gitlab().create_merge_request()

    else:
        raise Exception(f'unknown command {args.command}')


def main():
    def add_connection_args(parser):
        parser.add_argument('-d', '--dbname',
                            type=str, help='database name to connect to')
        parser.add_argument('-h', '--host',
                            type=str, help='database server host or socket directory')
        parser.add_argument('-p', '--port',
                            type=str, help='database server port')
        parser.add_argument('-U', '--user',
                            type=str, help='database user name')
        parser.add_argument('-W', '--password',
                            type=str, help='database user password')

    arg_parser = argparse.ArgumentParser(
        epilog='Report bugs: https://github.com/comagic/pg_migration/issues',
        conflict_handler='resolve',
        # usage='pg_migration [-h] command ...'
    )
    arg_parser.add_argument('--version',
                            action='version',
                            version=__version__)
    subparsers = arg_parser.add_subparsers(
        dest='command',
        title='commands'
    )

    parser_log = subparsers.add_parser(
        'log',
        help='print chain of migrations between from_version:to_version (or tail:head)'
    )
    parser_log.add_argument(
        '--no-multi-heads',
        required=False,
        action='store_true',
        help='raise error if multi heads detected'
    )
    parser_log.add_argument('version', help='from_version:to_version', nargs='?')

    parser_diff = subparsers.add_parser(
        'diff',
        help='show difference between database and specified (or last) version',
        conflict_handler='resolve',
    )
    add_connection_args(parser_diff)
    parser_diff.add_argument('version', help='difference between database and this version', nargs='?')

    parser_upgrade = subparsers.add_parser(
        'upgrade',
        help='upgrade database up to specified (or last) version',
        conflict_handler='resolve',
    )
    add_connection_args(parser_upgrade)
    parser_upgrade.add_argument('version', help='upgrade up to this version', nargs='?')
    parser_upgrade.add_argument('--timeout', type=int, default=0)
    parser_upgrade.add_argument(
        '--no-chain',
        required=False,
        action='store_true',
        help='error if any release in the migrations chain missed to apply to the DB'
    )
    parser_upgrade.add_argument(
        '--section',
        required=False,
        default='all',
        choices=['pre-release', 'release', 'post-release', 'all'],
        help='(default: all)'
    )
    parser_upgrade.add_argument(
        '--force',
        required=False,
        action='store_true',
        help='cancel blocking backends'
    )
    parser_upgrade.add_argument(
        '--distribute',
        required=False,
        action='store_true',
        help='distribute transaction on multi node (--node)'
    )
    parser_upgrade.add_argument(
        '--chain-migrations-path',
        type=dir_path,
        metavar='DIR_PATH',
        help='path to migrations for calculate migration chain for all nodes'
    )
    parser_upgrade.add_argument('--node', action='append', help=f'format: "{node_format}"', default=[])

    parser_generate = subparsers.add_parser(
        'generate',
        help='generate migration file'
    )
    parser_generate.add_argument(
        '--real-parent-release',
        required=False,
        action='store_true',
        help='add real parent_release, "--parent_release: auto" by default',
    )
    parser_generate.add_argument('version', help='new version', nargs='?')

    parser_plpgsql_check = subparsers.add_parser(
        'plpgsql_check',
        help='check functions and triggers with plpgsql_check extension',
        conflict_handler='resolve'
    )
    add_connection_args(parser_plpgsql_check)

    subparsers.add_parser(
        'auto_merge',
        help='creates merge-request when magic word "auto-commit" / "auto-deploy" is passed (uses in cd/cd)'
    )

    parser_init = subparsers.add_parser(
        'init',
        help='build migration which will create scheme migration and table migration.release',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser_init.add_argument('version', help='from_version:to_version', nargs='?', default='0.0')

    args = arg_parser.parse_args()
    args.dsn = build_dsn(args)

    if args.command == 'log' and args.version and ':' not in args.version:
        parser_log.error('version needs constant ":", use "pg_migration log -h" for more details')

    if args.command == 'upgrade':
        if args.distribute and not args.node:
            parser_upgrade.error('cannot use --distribute without any --node')
        if args.node and not args.distribute:
            parser_upgrade.error('cannot use --node without --distribute')
        if args.distribute and args.section == 'all':
            parser_upgrade.error('cannot use --section all with --distribute, you need upgrade each section separate')

    if not os.access('migrations', os.F_OK) and args.command != 'init':
        arg_parser.error('directory "migrations" not found')

    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    loop = asyncio.get_event_loop()
    loop.run_until_complete(run(args))
