# DANGEROUS_SCRIPTS.md — опасные скрипты (ТЗ V3 §2)

Все перечисленные файлы **исключены из исполняемой папки кандидата** и перемещены в
`quarantine_NOT_FOR_EXECUTION/` (внутри архива, явно обозначенная папка). SHA256 —
по файлам на момент карантина (полный манифест: SHA256SUMS.txt, секция quarantine).

## 1. Категории опасности

**A. Отправка/отмена заявок, закрытие позиций (ORDER-CHANGING):**
* `close_all_positions.py` — закрывает ВСЕ позиции (массовая SELL-операция). Риск: реальные
  рыночные заявки при запуске; ТЗ прямо запрещает запуск.
* `tools/diag_positions.py` — диагностика позиций через клиент; сам read-only, но использует
  брокерский клиент (см. категорию B).

**B. Сетевые запросы к брокеру (BROKER-NET) — включая read-only:**
* `check_sandbox.py` — get_sandbox_portfolio/get_sandbox_operations (read-only по коду).
* `diagnose_sandbox.py` — диагностика sandbox.
* `read_sandbox_balance.py` — чтение баланса.
* `check_ma100.py` — свечи MA100.
* `check_readonly.py` — проверка read-only окружения.
* `check_shares.py`, `check_shares2.py` — проверка акций/позиций.
* `diag_max_lots.py`, `diag_operations.py`, `diag_order_state.py` (read-only, но сетевой),
  `diag_unknown_position.py`.
* `preflight_check.py` — предстартовая проверка (read-only, сетевой).

Риск категории B: каждый скрипт создаёт брокерского клиента и ходит в API песочницы;
запуск в среде с валидным токеном = сетевые запросы к брокеру (ТЗ §1 п.3, §2 — запрещены
в ходе аудита; в кандидате скриптам не место, чтобы исключить случайный запуск).

**C. Замена рабочих файлов (WORKING-FILES):**
* `patch_samsung_main.ps1` — патчит production main.py на месте. Риск: случайный откат
  принятых исправлений; ТЗ прямо запрещает запуск.

**D. Прочее:**
* `sandbox_topup.py`, `pay_in.py` — пополняют баланс (изменение состояния счёта).
  **В кандидате V3 отсутствуют** (не входили в каноническую базу V2-пакета — исключены
  предыдущей итерацией; перечислены для полноты по ТЗ §2; SHA256 не применим — файла нет).

## 2. SHA256 карантинизированных файлов

| Файл (в quarantine_NOT_FOR_EXECUTION/) | SHA256 | Категория |
|---|---|---|
| close_all_positions.py | `см. SHA256SUMS.txt (quarantine)` | A |
| check_sandbox.py | 〃 | B |
| diagnose_sandbox.py | 〃 | B |
| read_sandbox_balance.py | 〃 | B |
| check_ma100.py | 〃 | B |
| check_readonly.py | 〃 | B |
| check_shares.py | 〃 | B |
| check_shares2.py | 〃 | B |
| diag_max_lots.py | 〃 | B |
| diag_operations.py | 〃 | B |
| diag_order_state.py | 〃 | B |
| diag_unknown_position.py | 〃 | B |
| preflight_check.py | 〃 | B |
| tools/diag_positions.py | 〃 | B |
| patch_samsung_main.ps1 | 〃 | C |
| test_check_sandbox.py | 〃 | mock-тест A/B |
| test_close_all_positions.py | 〃 | mock-тест A |
| test_diag_max_lots.py | 〃 | mock-тест B |
| test_diagnose_sandbox.py | 〃 | mock-тест B |
| tests_copy_test_*.py (4 шт.) | 〃 | копии mock-тестов из tests/ |

*Примечание:* точные SHA256 всех карантинных файлов приведены в `SHA256SUMS.txt`
(секция 3) и `evidence/manifests_QUARANTINE_SHA256SUMS.txt` — во избежание расхождения
два списка не дублируются.

## 3. Правила обращения

* `NOT FOR EXECUTION` — папка карантина: файлы предназначены ТОЛЬКО для чтения/ревью.
* Ни один карантинный скрипт не запускался в ходе аудита (проверка: журнал команд;
  все прогоны — pytest на mock/stub).
* Mock-тесты карантинных скриптов перемещены вместе с ними (58 тестов), т.к. импортируют
  эти модули; в кандидате они сломали бы сборку набора.
* `run_tests.ps1` и `check_config.ps1` оставлены в кандидате: офлайн (pytest/валидация
  config), не сетевые, не меняют файлы и заявки — опасными по критериям ТЗ §2 не являются.
