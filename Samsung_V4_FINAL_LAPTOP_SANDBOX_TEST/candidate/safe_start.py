# safe_start.py
# SAFE START / READ-ONLY — Режим A тестовой сборки V4 (ТЗ V4 §7.3).
# ЗАПУСК ПО УМОЛЧАНИЮ. Это НЕ main.py: торговый цикл не запускается.
#
# Что ДЕЛАЕТ (разрешено в Режиме A):
#   * проверяет зависимости и конфигурацию (fail-closed: отсутствующие
#     ключи/некорректные параметры -> понятный отказ, exit-код 2);
#   * проверяет активный режим сборки и ЗАЩИТУ ОТ ОТПРАВКИ ЗАЯВОК
#     (включая само-тест: попытка отправить заявку ОБЯЗАНА отклониться);
#   * проверяет доступность sandbox API только READ-ONLY запросами
#     (список аккаунтов, позиции); аккаунт НЕ создаётся (в отличие от
#     main.py, который создаёт его при первом запуске Режима B);
#   * проверяет локальные данные: реестр заявок (order_ledger.jsonl) и
#     локальное состояние (state.json);
#   * печатает диагностику (ТЗ §7.5) без токенов/секретов и корректно
#     завершается (штатная остановка).
#
# Что НЕ делает (запрещено в Режиме A):
#   * НЕ запускает trading_cycle / скринер / reconcile / telegram-бота;
#   * НЕ отправляет и НЕ отменяет заявки (BUY/SELL/отмена);
#   * НЕ изменяет баланс, позиции, аккаунты брокера;
#   * НЕ включает Режим B (см. enable_sandbox_execution.py и RUNBOOK).
#
# Использование:
#   python safe_start.py            # полная проверка (включая read-only API)
#   python safe_start.py --no-api   # без обращения к сети (только локально)
#
# Все сообщения — на русском; секреты не печатаются (только факт
# наличия настройки).

import asyncio
import importlib
import json
import os
import platform
import sys

import config
import build_safety
from order_ledger import OrderLedger

LEDGER_FILE = "order_ledger.jsonl"
STATE_FILE = "state.json"

SECRET_ENV_VARS = (
    "TINKOFF_API_TOKEN", "TINKOFF_READONLY_TOKEN", "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID", "TELEGRAM_ALLOWED_USER_ID", "TINKOFF_ACCOUNT_ID",
    "STARTING_BALANCE",
)

_OK, _WARN, _FAIL, _SKIP = "OK", "ВНИМАНИЕ", "ОТКАЗ", "ПРОПУЩЕНО"
_results = []  # (статус, компонент, деталь)


def _add(status, component, detail=""):
    _results.append((status, component, detail))
    mark = {_OK: "[ OK ]", _WARN: "[!! ]", _FAIL: "[FAIL]", _SKIP: "[SKIP]"}[status]
    print(f"  {mark} {component}: {detail}" if detail else f"  {mark} {component}")


def _check_dependencies():
    print("\n== 1. Зависимости ==")
    required = {"pandas": "обязательная", "dotenv": "обязательная",
                "pandas_ta_classic": "обязательная"}
    optional = {"telegram": "уведомления (робот работает и без неё)",
                "t_tech": "SDK брокера"}
    ok = True
    for mod, role in required.items():
        try:
            importlib.import_module(mod)
            _add(_OK, mod, f"{role} — найдена")
        except Exception as exc:
            ok = False
            _add(_FAIL, mod, f"{role} — ОТСУТСТВУЕТ ({type(exc).__name__})")
    for mod, role in optional.items():
        try:
            importlib.import_module(mod)
            _add(_OK, mod, f"{role} — найдена")
        except Exception:
            if mod == "t_tech":
                _add(_WARN, mod, f"{role} — нет (заглушки conftest только для тестов; "
                                 "для работы с брокером требуется requirements.txt)")
            else:
                _add(_WARN, mod, f"{role} — нет (робот работает без уведомлений)")
    return ok


def _check_configuration():
    print("\n== 2. Конфигурация ==")
    src = ".env (текущий каталог)" if os.path.isfile(".env") else \
        "переменные окружения процесса (.env в каталоге сборки не найден)"
    print(f"  источник конфигурации: {src}")
    for var in SECRET_ENV_VARS:
        state = "задана" if os.getenv(var) else "НЕ задана"
        print(f"    {var}: {state} (значение не выводится)")
    try:
        config.validate()
        _add(_OK, "config.validate()", "конфигурация валидна; sandbox-only подтверждён")
        return True
    except Exception as exc:
        _add(_FAIL, "config.validate()", f"безопасный отказ: {exc}")
        return False


def _check_mode_and_guard():
    print("\n== 3. Режим сборки и защита заявок ==")
    mode = build_safety.detect_mode()
    known = build_safety.mode_is_known()
    raw_env = (os.getenv(build_safety.MODE_ENV_VAR) or "").strip()
    if raw_env and not known:
        _add(_WARN, "SAMSUNG_V4_BUILD_MODE",
             f"неизвестное значение {raw_env!r} -> безопасно трактуется как {mode}")
    else:
        _add(_OK, "SAMSUNG_V4_BUILD_MODE", raw_env or "(не задана)")
    _add(_OK, "маркер Режима B", "присутствует" if build_safety.marker_present()
         else "отсутствует (Режим B выключен)")
    _add(_OK, "активный режим", mode)

    try:
        build_safety.assert_sandbox_only(config.USE_SANDBOX)
        _add(_OK, "sandbox-only", "USE_SANDBOX=True; LIVE запрещён")
    except Exception as exc:
        _add(_FAIL, "sandbox-only", str(exc))
        return None, False

    # Клиент + guard + само-тест блокировки
    from tinkoff_client import TinkoffClient
    from build_safety import OrderSubmissionDisabledError
    client = TinkoffClient(config.TINKOFF_API_TOKEN, config.USE_SANDBOX)
    guarded = build_safety.install_order_guard(client, mode)
    rep = build_safety.guard_report(client)
    if mode == build_safety.MODE_SANDBOX_EXECUTION:
        _add(_WARN, "Режим B активен",
             "заявки разрешены только в sandbox; убедитесь, что это осознанный запуск")
        return client, True
    _add(_OK, "guard заявок", f"установлен={guarded}; методы: {rep['guarded_methods']}")

    # Само-тест: попытка отправить заявку ОБЯЗАНА отклониться ДО сети
    # (guard подменяет метод обычной функцией — исключение возникает
    # синхронно, до создания coroutine и обращения к сети)
    try:
        client.post_market_order("SELFTEST_FIGI", 1, None, "safe-start-selftest")
        _add(_FAIL, "само-тест блокировки", "заявка НЕ отклонена — защита сломана!")
        return client, False
    except OrderSubmissionDisabledError as exc:
        _add(_OK, "само-тест блокировки", f"заявка отклонена: {str(exc)[:80]}...")
        return client, True
    except Exception as exc:
        _add(_FAIL, "само-тест блокировки", f"неожиданное исключение {type(exc).__name__}: {exc}")
        return client, False


async def _api_readonly_probe():
    """Только READ-ONLY: аккаунты и позиции. Аккаунт не создаётся."""
    from t_tech.invest.sandbox.async_client import AsyncSandboxClient
    print("\n== 4. Sandbox API (только чтение) ==")
    sbx = AsyncSandboxClient(config.TINKOFF_API_TOKEN)
    raw = None
    try:
        raw = await asyncio.wait_for(sbx.__aenter__(), timeout=30)
        _add(_OK, "подключение", "SANDBOX API доступен")
        accounts = await asyncio.wait_for(raw.users.get_accounts(), timeout=30)
        n = len(getattr(accounts, "accounts", []) or [])
        _add(_OK, "аккаунты", f"найдено: {n} (id не выводятся)")
        if n:
            acc_id = accounts.accounts[0].id
            positions = await asyncio.wait_for(
                raw.operations.get_positions(account_id=acc_id), timeout=30)
            securities = list(getattr(positions, "securities", []) or [])
            print(f"    позиций (securities) на первом аккаунте: {len(securities)} "
                  "(только чтение)")
        else:
            print("    sandbox-аккаунт отсутствует — SAFE START его НЕ создаёт; "
                  "аккаунт будет создан при первом штатном запуске (Режим B).")
        return True
    except Exception as exc:
        _add(_FAIL, "sandbox API", f"недоступен: {type(exc).__name__}: {exc}")
        return False
    finally:
        if raw is not None:
            try:
                await sbx.__aexit__(None, None, None)
            except Exception:
                pass


def _check_local_data():
    print("\n== 5. Локальные данные ==")
    # Реестр заявок
    try:
        ledger = OrderLedger(LEDGER_FILE)
        ledger.load()
        if ledger.is_reliable():
            latest = ledger.latest_all()
            open_n = len(ledger.open_orders())
            unc_n = sum(1 for r in latest.values() if r.get("status") == "UNCERTAIN")
            _add(_OK, "order_ledger.jsonl",
                 f"достоверен; записей: {len(latest)}, открытых заявок: {open_n}, UNCERTAIN: {unc_n}")
        else:
            _add(_WARN, "order_ledger.jsonl",
                 f"НЕДОСТОВЕРЕН: {ledger.unreliable_reason} (новые BUY будут заблокированы)")
    except Exception as exc:
        _add(_WARN, "order_ledger.jsonl", f"не прочитан: {type(exc).__name__}: {exc}")
    # Локальное состояние
    if not os.path.isfile(STATE_FILE):
        _add(_OK, "state.json", "отсутствует (чистый старт; при первом цикле будет создан)")
        return
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            _add(_FAIL, "state.json", "корневой объект не dict")
            return
        positions = data.get("positions", {})
        pos_n = len(positions) if isinstance(positions, dict) else "?"
        mon_err = bool(data.get("monitoring_error", False))
        rec_n = len(data.get("pending_csv_recoveries", []) or [])
        _add(_OK, "state.json",
             f"валидный JSON; позиций: {pos_n}; monitoring_error={mon_err}; "
             f"CSV-recovery задач: {rec_n}")
    except Exception as exc:
        _add(_FAIL, "state.json", f"повреждён: {type(exc).__name__}: {exc} "
                                  "(новые входы будут заблокированы до разбора)")


def main() -> int:
    _results.clear()  # каждый запуск диагностики начинается с чистого списка
    print("=" * 64)
    print("LAPTOP SANDBOX TEST BUILD — SAFE START / READ-ONLY (Режим A)")
    print("STRATEGY LOGIC: UNCHANGED | RESEARCH ONLY | NO LIVE ORDERS")
    print("BROKER ORDER SUBMISSION DISABLED BY DEFAULT")
    print("=" * 64)
    print(f"python: {platform.python_version()} | platform: {platform.system()}")
    print(f"сборка: {getattr(config, 'BUILD_VERSION', '?')} + V4 laptop-sandbox")
    print(f"каталог: {os.getcwd()}")
    no_api = "--no-api" in sys.argv

    overall = True
    overall &= _check_dependencies()
    overall &= _check_configuration()
    client, guard_ok = _check_mode_and_guard()
    overall &= guard_ok and client is not None
    if overall and not no_api:
        overall &= asyncio.run(_api_readonly_probe())
    elif no_api:
        print("\n== 4. Sandbox API (только чтение) ==")
        _add(_SKIP, "sandbox API", "--no-api: сетевые проверки отключены пользователем")
    _check_local_data()

    print("\n== Итог ==")
    failed = [r for r in _results if r[0] == _FAIL]
    warned = [r for r in _results if r[0] == _WARN]
    if failed:
        print(f"  БЕЗОПАСНЫЙ ОТКАЗ: {len(failed)} проверок завершились ошибкой:")
        for _, comp, det in failed:
            print(f"    - {comp}: {det}")
        print("  Запросы НЕ отправлялись; торговый цикл не запускался.")
        print("  Устраните причину (см. INSTALLATION_RU.md) и повторите safe_start.")
        return 2
    print("  SAFE START завершён: конфигурация, защита заявок и локальные "
          "данные проверены; заявки отключены; торговый цикл не запускался.")
    if warned:
        print(f"  предупреждений: {len(warned)} (см. пометки [!! ] выше)")
    print("  Следующие шаги — LAPTOP_TEST_RUNBOOK_RU.md (§7 и далее).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nШтатная остановка (Ctrl+C): проверки прерваны пользователем; "
              "заявки не отправлялись.")
        sys.exit(130)
