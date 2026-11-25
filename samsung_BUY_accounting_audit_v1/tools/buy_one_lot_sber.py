# buy_one_lot_sber.py
# РАЗОВАЯ покупка 1 лота SBER в SANDBOX — только для диагностики quantity.
# НЕ торговый цикл. Отправляет ОДНУ рыночную заявку.
# Запускать вручную, один раз. Удалить после диагностики.

import asyncio
import logging

from t_tech.invest import OrderDirection, OrderType, InstrumentIdType

import config
from tinkoff_client import TinkoffClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


async def main():
    async with TinkoffClient(config.TINKOFF_API_TOKEN, config.USE_SANDBOX) as client:
        # 1. Найти SBER по тикеру
        resp = await client.client.instruments.get_instrument_by(
            id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_TICKER,
            id="SBER",
            class_code="TQBR",
        )
        instrument = resp.instrument
        figi = instrument.figi
        ticker = instrument.ticker
        lot = int(instrument.lot or 1)
        logging.info(f"Инструмент: {ticker} figi={figi} lot={lot}")

        # 2. Получить последнюю цену
        prices = await client.get_last_prices([figi])
        price = prices.get(figi)
        if not price:
            logging.error("Нет цены SBER — возможно, биржа закрыта. Попробуйте в торговые часы MOEX.")
            return
        logging.info(f"Последняя цена: {price:.4f} ₽, стоимость 1 лота ≈ {price * lot:.2f} ₽")

        # 3. Купить 1 лот (quantity=1 — это ЛОТЫ, не акции)
        order = await client.post_market_order(
            figi=figi, quantity=1,
            direction=OrderDirection.ORDER_DIRECTION_BUY,
        )
        if order is None:
            logging.error("Заявка не отправлена — см. ошибку выше.")
            return
        logging.info(f"Заявка отправлена: order_id={getattr(order, 'order_id', None)}")
        logging.info(f"Статус: {getattr(order, 'execution_report_status', None)}")
        logging.info("Готово. Теперь запустите: python diag_positions.py")


if __name__ == "__main__":
    asyncio.run(main())