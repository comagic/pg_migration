from .pg import Pg


class PlpgsqlChecker:
    pg: Pg

    def __init__(self, pg):
        self.pg = pg

    async def check(self):
        exit(await self.check_functions() + await self.check_triggers())

    async def check_functions(self):
        errors = await self.pg.plpgsql_check_functions()
        if len(errors) == 0:
            print('functions: ok')
            return 0
        print('functions:')
        for e in errors:
            print(f"{e['func']}: {e['error']}")
        return 1

    async def check_triggers(self):
        errors = await self.pg.plpgsql_check_triggers()
        if len(errors) == 0:
            print('triggers: ok')
            return 0
        print('triggers:')
        for e in errors:
            print(f"{e['func']} on {e['rel']}: {e['error']}")
        return 1
