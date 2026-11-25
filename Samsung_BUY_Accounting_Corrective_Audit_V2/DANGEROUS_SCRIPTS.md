# DANGEROUS_SCRIPTS.md — опасные скрипты и решения по упаковке

Мандаты: `RESEARCH ONLY` · `NO LIVE ORDERS` · `NO SANDBOX ORDERS`.
Ни один из перечисленных скриптов НЕ запускался в ходе аудита
(выполнялся только pytest на mock/stub-клиентах).

Инвентаризация выполнена заново на неизменённом кандидате
(Samsung_BUY_Accounting_Audit_V1); классификация согласована с
предыдущим независимым аудитом (Samsung_Independent_Audit, 2026-11-25).

---

## 1. Скрипты, способные отправить заявки / изменить счёт

| Скрипт (в ИСХОДНОМ пакете) | Действие | Защиты | Решение для candidate/ |
|---|---|---|---|
| `close_all_positions.py` | РУЧНОЕ аварийное закрытие: отправляет SELL в песочнице (`post_market_order` через `TinkoffClient(use_sandbox=True)`) | проверка USE_SANDBOX (только песочница); интерактивное подтверждение `YES`; шапка «ТОЛЬКО SANDBOX» | **ОСТАВЛЕН** в candidate/ — техническая необходимость: импортируется существующими тестами `test_close_all_positions.py` (root + tests/); исключение сломало бы 2 существующих теста (запрещено ТЗ §8/§11.7). **НЕ ЗАПУСКАТЬ**; в исполняемый набор аудита не входит |
| `pay_in.py` | Пополнение счёта песочницы на 100 000 ₽ (`sandbox.pay_in`) | проверка USE_SANDBOX; проверка TINKOFF_ACCOUNT_ID; интерактивное подтверждение | **ИСКЛЮЧЁН** из candidate/ (ТЗ §10) |
| `sandbox_topup.py` | Доведение баланса песочницы до 100 000 ₽; **без интерактивного подтверждения**; захардкоженный ACCOUNT_ID `538f670d-…` (дефект R-5) | проверка USE_SANDBOX через config; сверка ACCOUNT_ID | **ИСКЛЮЧЁН** из candidate/ (ТЗ §10) |
| `tools/buy_one_lot_sber.py` | Отправка РУЧНОЙ BUY-заявки (SBER, песочница) | — (ручной запуск) | **ИСКЛЮЧЁН** из candidate/ (ТЗ §10) |
| `start_after_tests.ps1` | pytest → при успехе и вводе оператором `SANDBOX` → запуск `main.py` (торговый цикл) | подтверждение оператором; тесты должны пройти | **ИСКЛЮЧЁН** из candidate/ (ТЗ §10 — запуск торгового робота) |
| `main.py` | Торговый робот (trading_cycle, BUY/SELL) | торговля ТОЛЬКО при `trading.flag` (создаётся Telegram /start); авто-старт при импорте отсутствует (проверено: import main безопасен — все 41 BUY-тест и полный набор импортируют его) | **ОСТАВЛЕН** — это и есть production-файл кандидата (ТЗ §12: «полный кандидат», «не заменять исходники diff-ами»); не запускался |
| `telegram_bot.py` | /start создаёт trading.flag, /stop удаляет; авторизация по ALLOWED_USER_ID | авторизация; 3 команды | **ОСТАВЛЕН** — импортируется main.py (lazy, main.py:577); не запускался |

## 2. Скрипты, изменяющие файлы (не заявки)

| Скрипт | Действие | Решение |
|---|---|---|
| `patch_samsung_main.ps1` | Скачивает main.py из GitHub raw и ЗАМЕНЯЕТ локальный файл (проверка git-blob SHA1) | ОСТАВЛЕН в candidate/ (не отправляет заявок; часть исходного пакета); не выполнялся |
| `run_tests.ps1` | pytest из .venv в корне пакета | ОСТАВЛЕН; предупреждение: запуск в корне пакета дописывает события в research_events.jsonl (U-2) — использовать копию |
| `check_config.ps1` | Вывод конфигурации | безопасен |

## 3. READ-ONLY диагностика (проверено предыдущим аудитом, подтверждено)

`check_ma100.py`, `check_readonly.py`, `check_sandbox.py`, `check_shares.py`,
`check_shares2.py`, `diag_max_lots.py`, `diag_operations.py`,
`diag_order_state.py`, `diag_unknown_position.py`, `diagnose_sandbox.py`,
`preflight_check.py`, `read_sandbox_balance.py`, `tools/diag_positions.py` —
без мутаций счёта/заявок. Оставлены в candidate/ как часть пакета.

## 4. Исключено из candidate/ по ТЗ §10 (с фиксацией)

| Категория | Файлы | Основание |
|---|---|---|
| Order/account-скрипты | `pay_in.py`, `sandbox_topup.py`, `tools/buy_one_lot_sber.py`, `start_after_tests.ps1` | §10: «скрипты, способные отправлять реальные или sandbox-ордера» / запуск торгового робота |
| Runtime-файлы пользователя | `state.json`, `order_ledger.jsonl`, `research_events.jsonl`, `research_trades.csv`, `sandbox_pnl.csv` | §10: runtime-состояние, реальные CSV/JSONL-истории; создаются при первом запуске |
| Backup/reset-архивы | `RESET_ARCHIVE_20261121_232758/` (+.7z), `RESET_ARCHIVE_CLEAN_START_20261123_133004/` (+.7z), `RESET_BACKUP_20261121/` (+.7z), `AUDIT_9_FAILURES.zip` | §10: backup/reset-архивы |
| Вложенные пакеты с runtime-данными | `Samsung_B2_Integrated_V1_V7.zip`, `Samsung_BUY_Accounting_Audit_V1.zip` | содержат runtime-состояние/истории (§10) |

Все исключённые файлы СОХРАНЕНЫ в неизменном ИСХОДНОМ пакете
(Samsung_BUY_Accounting_Audit_V1 — не модифицировался); их состав и
назначение зафиксированы выше. Исходный кандидат не удалялся и не менялся.

## 5. Проверка архива на секреты и runtime-загрязнение

* Секретов (токены/ключи/пароли) в candidate/ НЕТ: production читает их из
  переменных окружения (config.py через os.environ/dotenv); grep по
  паттернам «token/secret/password = literal» — пусто. Единственный
  захардкоженный идентификатор счёта (`sandbox_topup.py`) исключён из
  candidate/ (см. §4); `.env`-файлов в пакете нет.
* Runtime-загрязнения в candidate/ нет: runtime-файлы исключены (§4);
  копии тестовых state/events в архив не попали (проверено списком файлов).
* Тестовые файлы с вызовами post_market_order (unit-тесты) используют
  fake-клиенты и НЕ выполняют сетевых вызовов (подтверждено полным прогоном).

## 6. Итоговая классификация

| Уровень | Скрипты |
|---|---|
| Отправляют заявки / меняют счёт (исключены из candidate/) | `pay_in.py`, `sandbox_topup.py`, `tools/buy_one_lot_sber.py`, `start_after_tests.ps1` |
| Отправляет заявки (оставлен — зависимость тестов; НЕ ЗАПУСКАТЬ) | `close_all_positions.py` |
| Запуск торгового робота (оставлен как production; не запускался) | `main.py` (только при trading.flag), `telegram_bot.py` |
| Изменяют файлы | `patch_samsung_main.ps1`, `run_tests.ps1` (предупреждение о копии) |
| READ-ONLY | все `check_*`, `diag_*`, `preflight_check.py`, `read_sandbox_balance.py`, `tools/diag_positions.py` |
