# test_v4_safety_build.py
# V4 (ТЗ §7, §8): безопасное ядро laptop-сборки.
#   * режим A (SAFE START / READ-ONLY) — по умолчанию, заявки заблокированы;
#   * режим B — только маркер + env, LIVE запрещён всегда;
#   * guard технически блокирует post_market_order/cancel_order на клиенте;
#   * safe_start.py — read-only входная точка с fail-closed диагностикой;
#   * проверки чистого окружения (импорт main без сети, py_compile,
#     fail-closed конфигурации).
# Все тесты локальные, mock/stub, без сетевых операций (ТЗ §0.14).

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import build_safety
from build_safety import (
    MODE_SAFE_START,
    MODE_SANDBOX_EXECUTION,
    OrderSubmissionDisabledError,
    assert_sandbox_only,
    detect_mode,
    install_order_guard,
    marker_present,
    mode_is_known,
    orders_allowed,
)

# Корень кандидата (тесты могут выполняться с cwd=tmp_path — все файловые
# и subprocess-проверки используют АБСОЛЮТНЫЙ путь сборки).
CAND = Path(__file__).resolve().parent


class _FakeClient:
    """Минимальный двойник TinkoffClient для проверки guard'а."""

    def __init__(self):
        self.post_market_order = lambda *a, **k: "REAL_ORDER_SENT"
        self.cancel_order = lambda *a, **k: "REAL_CANCEL_SENT"
        self.uncertain_state = False


@pytest.fixture(autouse=True)
def _clean_mode_env(monkeypatch, tmp_path):
    monkeypatch.delenv(build_safety.MODE_ENV_VAR, raising=False)
    monkeypatch.chdir(tmp_path)
    yield


# ---------------------------------------------------------------------
# Режимы (ТЗ §7.3): default SAFE_START; B — только маркер + env; fail-closed
# ---------------------------------------------------------------------

def test_default_mode_is_safe_start():
    assert detect_mode() == MODE_SAFE_START
    assert orders_allowed() is False
    assert marker_present() is False


def test_mode_b_requires_marker_and_env(monkeypatch):
    # только env без маркера -> SAFE_START
    monkeypatch.setenv(build_safety.MODE_ENV_VAR, MODE_SANDBOX_EXECUTION)
    assert detect_mode() == MODE_SAFE_START
    # только маркер без env -> SAFE_START
    monkeypatch.delenv(build_safety.MODE_ENV_VAR)
    Path(build_safety.MARKER_FILE).write_text("enabled_at_utc=now\n")
    assert detect_mode() == MODE_SAFE_START
    # оба условия -> SANDBOX_EXECUTION
    monkeypatch.setenv(build_safety.MODE_ENV_VAR, MODE_SANDBOX_EXECUTION)
    assert detect_mode() == MODE_SANDBOX_EXECUTION
    assert orders_allowed() is True


def test_unknown_env_value_fail_closed(monkeypatch):
    monkeypatch.setenv(build_safety.MODE_ENV_VAR, "LIVE")
    Path(build_safety.MARKER_FILE).write_text("x\n")
    assert detect_mode() == MODE_SAFE_START  # опечатка не включает заявки
    assert mode_is_known() is False
    monkeypatch.setenv(build_safety.MODE_ENV_VAR, "sandbox_execution")  # регистронезависимо
    assert detect_mode() == MODE_SANDBOX_EXECUTION
    assert mode_is_known() is True


def test_env_safe_start_value_is_known(monkeypatch):
    monkeypatch.setenv(build_safety.MODE_ENV_VAR, MODE_SAFE_START)
    assert detect_mode() == MODE_SAFE_START
    assert mode_is_known() is True


def test_live_is_hard_blocked_at_client_and_config_levels():
    # уровень 1: assert_sandbox_only
    with pytest.raises(RuntimeError, match="LIVE запрещён"):
        assert_sandbox_only(False)
    assert_sandbox_only(True)  # не поднимает
    # уровень 2/3: TinkoffClient и config.validate() (см. test_safety.py/
    # test_trading_flag.py и production-код; здесь — контракт build_safety)
    from tinkoff_client import SandboxRequiredError, TinkoffClient
    with pytest.raises(SandboxRequiredError):
        TinkoffClient("token", use_sandbox=False)


# ---------------------------------------------------------------------
# Guard заявок (ТЗ §7.3): блокировка отправки/отмены на экземпляре
# ---------------------------------------------------------------------

def test_guard_blocks_post_and_cancel_in_safe_start():
    client = _FakeClient()
    installed = install_order_guard(client, MODE_SAFE_START)
    assert installed is True
    with pytest.raises(OrderSubmissionDisabledError):
        client.post_market_order("FIGI", 1, None, "oid")
    with pytest.raises(OrderSubmissionDisabledError):
        client.cancel_order("oid")
    # исключение поднимается до сети: метод заменён функцией, coroutine
    # не создаётся и брокер не получает вызова


def test_guard_not_installed_in_mode_b():
    Path(build_safety.MARKER_FILE).write_text("x\n")
    monkeypatch_setenv = os.environ.__setitem__
    old = os.environ.get(build_safety.MODE_ENV_VAR)
    os.environ[build_safety.MODE_ENV_VAR] = MODE_SANDBOX_EXECUTION
    try:
        client = _FakeClient()
        installed = install_order_guard(client)
        assert installed is False
        assert client.post_market_order("FIGI", 1, None, "oid") == "REAL_ORDER_SENT"
        assert client.cancel_order("oid") == "REAL_CANCEL_SENT"
    finally:
        if old is None:
            os.environ.pop(build_safety.MODE_ENV_VAR, None)
        else:
            monkeypatch_setenv(build_safety.MODE_ENV_VAR, old)


def test_guard_is_idempotent():
    client = _FakeClient()
    assert install_order_guard(client, MODE_SAFE_START) is True
    assert install_order_guard(client, MODE_SAFE_START) is False
    with pytest.raises(OrderSubmissionDisabledError):
        client.post_market_order("FIGI", 1, None, "oid")


def test_guard_report_no_secrets():
    client = _FakeClient()
    install_order_guard(client, MODE_SAFE_START)
    rep = build_safety.guard_report(client)
    assert rep["guard_installed"] is True
    assert rep["mode"] == MODE_SAFE_START
    assert rep["orders_allowed"] is False
    assert set(rep["guarded_methods"]) == {"post_market_order", "cancel_order"}


def test_main_source_installs_guard_and_safe_start_has_no_trading_loop():
    """Контракт сборки: guard подключён в main(); safe_start не содержит
    торгового цикла/скринера/reconcile (ТЗ §8.14 — «нет скрытого запуска
    торгового цикла»)."""
    main_src = (CAND / "main.py").read_text(encoding="utf-8")
    assert "build_safety.install_order_guard(client)" in main_src
    assert "build_safety.assert_sandbox_only(config.USE_SANDBOX)" in main_src
    safe_src = (CAND / "safe_start.py").read_text(encoding="utf-8")
    # запрет на ВЫЗОВЫ (в комментариях/докстрингах упоминания допустимы)
    assert "trading_cycle(" not in safe_src
    assert "Screener(" not in safe_src
    assert "reconcile(" not in safe_src
    assert "startup_recovery(" not in safe_src
    assert "process_closing(" not in safe_src
    assert "promote_recovery_positions(" not in safe_src
    assert "poll_open_orders(" not in safe_src


# ---------------------------------------------------------------------
# safe_start.py (ТЗ §7.3 Режим A, §7.5 диагностика)
# ---------------------------------------------------------------------

@pytest.fixture
def _configured(monkeypatch):
    monkeypatch.setattr("config.TINKOFF_API_TOKEN", "test-token-not-real")
    monkeypatch.setattr("config.TINKOFF_READONLY_TOKEN", "test-ro")
    monkeypatch.setattr("config.TELEGRAM_BOT_TOKEN", "test-tg")
    monkeypatch.setattr("config.TELEGRAM_CHAT_ID", "123")
    monkeypatch.setattr("config.TELEGRAM_ALLOWED_USER_ID", "1")
    monkeypatch.setattr(sys, "argv", ["safe_start.py", "--no-api"])
    yield


def test_safe_start_passes_in_clean_dir(_configured, capsys):
    import safe_start
    rc = safe_start.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "SAFE START / READ-ONLY" in out
    assert "BROKER ORDER SUBMISSION DISABLED BY DEFAULT" in out
    assert "само-тест блокировки" in out  # заявка отклонена guard'ом
    assert "STRATEGY LOGIC: UNCHANGED" in out


def test_safe_start_fail_closed_without_token(monkeypatch, _configured, capsys):
    monkeypatch.setattr("config.TINKOFF_API_TOKEN", None)
    import safe_start
    rc = safe_start.main()
    out = capsys.readouterr().out
    assert rc == 2
    assert "БЕЗОПАСНЫЙ ОТКАЗ" in out
    assert "TINKOFF_API_TOKEN" in out


def test_safe_start_reports_mode_b_as_warning(_configured, monkeypatch, capsys):
    Path(build_safety.MARKER_FILE).write_text("x\n")
    monkeypatch.setenv(build_safety.MODE_ENV_VAR, MODE_SANDBOX_EXECUTION)
    import safe_start
    rc = safe_start.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "Режим B активен" in out


def test_safe_start_does_not_print_secrets(_configured, monkeypatch, capsys):
    monkeypatch.setenv("TINKOFF_API_TOKEN", "super-secret-token-value-123")
    import safe_start
    safe_start.main()
    out = capsys.readouterr().out
    assert "super-secret-token-value-123" not in out
    assert "задана (значение не выводится)" in out


# ---------------------------------------------------------------------
# Чистое окружение (ТЗ §8): компиляция, импорт, fail-closed конфигурация
# ---------------------------------------------------------------------

PRODUCTION_FILES = [
    "main.py", "config.py", "logger.py", "execution.py", "order_ledger.py",
    "strategy.py", "risk_manager.py", "screener.py", "telegram_bot.py",
    "tinkoff_client.py", "build_safety.py", "safe_start.py",
    "enable_sandbox_execution.py",
]

REQUIRED_CANDIDATE_FILES = PRODUCTION_FILES + [
    "conftest.py", "requirements.txt", "test_v4_order_ledger_first_append.py",
    "test_v4_safety_build.py",
]


def test_all_production_files_compile():
    for name in PRODUCTION_FILES:
        assert (CAND / name).is_file(), f"файл отсутствует: {name}"
        rc = subprocess.run([sys.executable, "-m", "py_compile", name],
                            capture_output=True, text=True, cwd=CAND)
        assert rc.returncode == 0, f"{name} не компилируется: {rc.stderr}"


def test_required_candidate_files_present():
    for name in REQUIRED_CANDIDATE_FILES:
        assert (CAND / name).is_file(), f"обязательный файл отсутствует: {name}"


def test_main_imports_cleanly_with_stubs_subprocess():
    """Импорт main.py в чистом subprocess с заглушками (нет циклов/сбоев,
    нет сетевых вызовов — импорт не подключается к брокеру)."""
    code = textwrap.dedent("""
        import sys
        sys.path.insert(0, ".")
        from tests.conftest import _install_stubs
        _install_stubs()
        import main
        print("MAIN_IMPORT_OK")
    """)
    rc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                        text=True, timeout=120, cwd=CAND)
    assert rc.returncode == 0, rc.stderr[-2000:]
    assert "MAIN_IMPORT_OK" in rc.stdout


def test_config_validate_fails_closed_without_env_subprocess(tmp_path):
    """Чистая среда без ключей: config.validate() обязан отказать."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("TINKOFF_API_TOKEN", "TINKOFF_READONLY_TOKEN",
                        "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
                        "TELEGRAM_ALLOWED_USER_ID")}
    rc = subprocess.run([sys.executable, "-c",
                         "import config; config.validate()"],
                        capture_output=True, text=True, env=env, timeout=60,
                        cwd=CAND)
    assert rc.returncode != 0
    assert "Не заданы" in rc.stderr
