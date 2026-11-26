# enable_sandbox_execution.py
# Режим B — CONTROLLED SANDBOX EXECUTION: инструмент ЯВНОГО включения
# (ТЗ V4 §7.3). По умолчанию Режим B ВЫКЛЮЧЕН; этот скрипт создаёт
# файл-маркер sandbox_execution.enabled ПОСЛЕ интерактивного подтверждения.
#
# ВАЖНО:
#   * LIVE остаётся запрещённым ВСЕГДА (TinkoffClient и config.validate()
#     отклоняют use_sandbox=False при любых обстоятельствах);
#   * маркер сам по себе заявки не включает: для активного Режима B нужно
#     ОДНОВРЕМЕННО (a) наличие маркера и (b) запуск процесса с переменной
#     окружения SAMSUNG_V4_BUILD_MODE=SANDBOX_EXECUTION;
#   * случайное значение конфигурации или опечатка не включают заявки
#     (build_safety.detect_mode трактует всё неизвестное как SAFE_START).
#
# Запуск GLM НЕ выполнял и выполнять не вправе (ТЗ §7.3): инструмент
# подготовлен и задокументирован, но оставлен неактивированным.
#
# Использование (см. LAPTOP_TEST_RUNBOOK_RU.md, раздел «Режим B»):
#   python enable_sandbox_execution.py

import datetime
import os
import sys

MARKER_FILE = "sandbox_execution.enabled"
CONFIRM_PHRASE = "ENABLE-SANDBOX"


def main() -> int:
    print("=" * 64)
    print("ВКЛЮЧЕНИЕ РЕЖИМА B — CONTROLLED SANDBOX EXECUTION")
    print("=" * 64)
    print("Этот шаг разрешает отправку SANDBOX-заявок при запуске main.py с")
    print("переменной окружения SAMSUNG_V4_BUILD_MODE=SANDBOX_EXECUTION.")
    print("LIVE-режим останется технически запрещённым при любых условиях.")
    print()
    if os.path.isfile(MARKER_FILE):
        print(f"Маркер {MARKER_FILE} уже существует — повторное включение не требуется.")
        return 0
    try:
        answer = input(f"Для включения введите точно {CONFIRM_PHRASE} и нажмите Enter: ").strip()
    except KeyboardInterrupt:
        print("\nОтменено пользователем. Маркер НЕ создан.")
        return 130
    if answer != CONFIRM_PHRASE:
        print("Фраза не совпала — включение ОТМЕНЕНО. Маркер НЕ создан.")
        return 1
    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with open(MARKER_FILE, "w", encoding="utf-8") as f:
        f.write(f"enabled_at_utc={stamp}\n"
                "mode=SANDBOX_EXECUTION\n"
                "live=FORBIDDEN\n"
                "note=Created manually by operator (enable_sandbox_execution.py)\n")
    print()
    print(f"Маркер создан: {os.path.abspath(MARKER_FILE)}")
    print()
    print("Чтобы запустить Режим B, выполняйте main.py В ЭТОМ каталоге с переменной окружения,")
    print("например в PowerShell:")
    print('  $env:SAMSUNG_V4_BUILD_MODE = "SANDBOX_EXECUTION"')
    print("  python main.py")
    print()
    print("Без этой переменной окружения (или после закрытия терминала) заявки")
    print("снова заблокированы — Режим B не сохраняется между сессиями.")
    print("Чтобы вернуть сборку в Режим A: удалите файл-маркер:")
    print(f"  Remove-Item {MARKER_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
