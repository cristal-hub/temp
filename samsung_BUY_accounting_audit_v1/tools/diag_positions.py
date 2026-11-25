# diag_positions.py
# ДИАГНОСТИКА: сырые quantity / quantity_lots по позициям.
# НЕ используется торговой логикой. Только для ручной проверки.

import asyncio
import json

import config
from tinkoff_client import TinkoffClient


async def main():
    async with TinkoffClient(config.TINKOFF_API_TOKEN, config.USE_SANDBOX) as c:
        print("account_id:", c.account_id)
        rows = await c.get_positions_debug()
        print(f"Позиций: {len(rows)}")
        for row in rows:
            print(json.dumps(row, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())