import os
import argparse
import asyncio

from .migration import Migration
from .pg import Pg
from .release_generator import ReleaseGenerator
from .upgrader import Upgrader


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
        pg = Pg(args)
        await pg.init_connection()
        migration = Migration(args, pg)
        await Upgrader(args, migration, pg).upgrade()

    else:
        raise Exception(f'unknown command {args.command}')


def build_dsn(args):
    parts = []
    if args.host:
        parts.append(f'host={args.host}')
    if args.port:
        parts.append(f'port={args.port}')
    if args.dbname:
        parts.append(f'dbname={args.dbname}')
    if args.user:
        parts.append(f'user={args.user}')
    if args.password:
        parts.append(f'password={args.password}')
    return ' '.join(parts)


def main():
    arg_parser = argparse.ArgumentParser(
        description='Migration control system',
        epilog='Report bugs to <andruuche@gmail.com>.',
        conflict_handler='resolve')
    arg_parser.add_argument('command', help='diff | upgrade | generate | log')
    arg_parser.add_argument('-d', '--dbname',
                            type=str, help='database name to connect to')
    arg_parser.add_argument('-h', '--host',
                            type=str, help='database server host or socket directory')
    arg_parser.add_argument('-p', '--port',
                            type=str, help='database server port')
    arg_parser.add_argument('-U', '--user',
                            type=str, help='database user name')
    arg_parser.add_argument('-W', '--password',
                            type=str, help='database user password')
    arg_parser.add_argument('migration', help='migration filename', default='head', nargs='?')
    args = arg_parser.parse_args()
    args.dsn = build_dsn(args)

    if not os.access('migrations', os.F_OK):
        arg_parser.error('directory "migrations" not found')

    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    loop = asyncio.get_event_loop()
    loop.run_until_complete(run(args))
