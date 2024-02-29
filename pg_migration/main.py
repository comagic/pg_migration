import os
import argparse
import asyncio

from .migration import Migration
from .pg import Pg


async def run(args):
    if args.command == 'diff':
        pg = Pg(args)
        await pg.init_connection()
        await Migration(args, pg).print_diff()

    elif args.command == 'log':
        await Migration(args, None).print_log()


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

    if not os.access('migrations', os.F_OK):
        arg_parser.error('directory "migrations" not found')

    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    loop = asyncio.get_event_loop()
    loop.run_until_complete(run(args))
