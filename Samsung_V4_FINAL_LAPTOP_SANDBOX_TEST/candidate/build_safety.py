# build_safety.py
# LAPTOP SANDBOX TEST BUILD — BROKER ORDER SUBMISSION DISABLED BY DEFAULT
#
# Безопасное ядро тестовой сборки V4 (ТЗ V4 §7.3): техническое разделение
# режимов БЕЗ изменения торговой логики, сигналов, фильтров и рисков.
#
#   Режим A — SAFE START / READ-ONLY (ПО УМОЛЧАНИЮ):
#       отправка заявок (post_market_order) и отмена заявок (cancel_order)
#       технически ЗАБЛОКИРОВАНЫ на уровне экземпляра клиента:
#       install_order_guard(client) подменяет эти методы защитными, которые
#       поднимают OrderSubmissionDisabledError ДО любого обращения к сети.
#       Ни BUY, ни SELL, ни отмена не могут достигнуть брокера.
#
#   Режим B — CONTROLLED SANDBOX EXECUTION (по умолчанию ВЫКЛЮЧЕН):
#       включается ТОЛЬКО одновременным выполнением ДВУХ явных условий:
#         1) файл-маркер sandbox_execution.enabled в корне сборки
#            (создаётся скриптом enable_sandbox_execution.py после
#            интерактивного подтверждения оператором);
#         2) переменная окружения SAMSUNG_V4_BUILD_MODE=SANDBOX_EXECUTION
#            в запускаемом процессе.
#       Отсутствие ЛЮБОГО из двух условий -> заявки заблокированы.
#       Случайное значение конфигурации режим не включает.
#
#   LIVE запрещён ВСЕГДА (три независимых уровня):
#         1) TinkoffClient.__init__ поднимает SandboxRequiredError при
#            use_sandbox=False;
#         2) config.validate() поднимает RuntimeError при USE_SANDBOX=False;
#         3) assert_sandbox_only() — явная проверка сборки.
#       Никаких автоматических переключений Sandbox<->LIVE нет.
#
# Неизвестное/невалидное значение SAMSUNG_V4_BUILD_MODE безопасно
# трактуется как SAFE_START (fail-closed): опечатка не может включить заявки.

import os

MODE_SAFE_START = "SAFE_START"
MODE_SANDBOX_EXECUTION = "SANDBOX_EXECUTION"
MODE_ENV_VAR = "SAMSUNG_V4_BUILD_MODE"
MARKER_FILE = "sandbox_execution.enabled"

GUARDED_METHODS = ("post_market_order", "cancel_order")


class OrderSubmissionDisabledError(RuntimeError):
    """Поднимается вместо отправки/отмены заявки в режиме SAFE_START."""


def marker_present(root: str = ".") -> bool:
    return os.path.isfile(os.path.join(root, MARKER_FILE))


def detect_mode(root: str = ".") -> str:
    """Единственный источник истины о режиме сборки (fail-closed).

    SANDBOX_EXECUTION возможен ТОЛЬКО при env=SANDBOX_EXECUTION И наличии
    маркер-файла. Любое другое сочетание (в т.ч. неизвестное значение env,
    отсутствие env при наличии маркера) -> SAFE_START.
    """
    raw = (os.getenv(MODE_ENV_VAR) or "").strip().upper()
    if raw == MODE_SANDBOX_EXECUTION and marker_present(root):
        return MODE_SANDBOX_EXECUTION
    return MODE_SAFE_START


def mode_is_known(root: str = ".") -> bool:
    """True, если значение env (если задано) распознано — для диагностики."""
    raw = (os.getenv(MODE_ENV_VAR) or "").strip().upper()
    return raw in ("", MODE_SAFE_START, MODE_SANDBOX_EXECUTION)


def orders_allowed(mode: str = None) -> bool:
    """Заявки разрешены только в Режиме B (см. detect_mode)."""
    if mode is None:
        mode = detect_mode()
    return mode == MODE_SANDBOX_EXECUTION


def assert_sandbox_only(use_sandbox) -> None:
    """Третий независимый уровень блокировки LIVE (для диагностики сборки)."""
    if not use_sandbox:
        raise RuntimeError(
            "LAPTOP SANDBOX TEST BUILD: LIVE запрещён. USE_SANDBOX=False "
            "недопустим в тестовой сборке (sandbox-only).")


def install_order_guard(client, mode: str = None) -> bool:
    """Отключает отправку/отмену заявок на ЭКЗЕМПЛЯРЕ клиента (Режим A).

    Возвращает True, если установлен защитный барьер (заявки заблокированы);
    False — если режим B активен (production-поведение unchanged) или guard
    уже установлен (идемпотентно). Экземплярные атрибуты перекрывают методы
    класса, поэтому защитой охватываются ВСЕ вызывающие пути main.py
    (register_executed_buy, close_position, poll_open_orders и др.).
    """
    if getattr(client, "_v4_order_guard_installed", False):
        return False
    if mode is None:
        mode = detect_mode()
    client._v4_order_guard_installed = True
    client._v4_order_guard_mode = mode
    if orders_allowed(mode):
        return False

    def _blocked(*args, **kwargs):
        raise OrderSubmissionDisabledError(
            "LAPTOP SANDBOX TEST BUILD: операция с заявками отклонена "
            f"(активный режим: {mode}, отправка заявок отключена по "
            "умолчанию). Включение Режима B — только по процедуре "
            "LAPTOP_TEST_RUNBOOK_RU.md (§ Режим B).")

    for name in GUARDED_METHODS:
        setattr(client, name, _blocked)
    return True


def guard_report(client) -> dict:
    """Диагностика состояния guard'а (без секретов)."""
    return {
        "guard_installed": bool(getattr(client, "_v4_order_guard_installed", False)),
        "mode": getattr(client, "_v4_order_guard_mode", detect_mode()),
        "orders_allowed": orders_allowed(getattr(client, "_v4_order_guard_mode", None)),
        "guarded_methods": list(GUARDED_METHODS),
    }
