# tests/ — копии V4-аудит-тестов для независимой проверки

Канонические (исполняемые) версии всех тестов находятся в `candidate/` —
полная самостоятельная тестовая сборка. Файлы в этом каталоге — байт-в-байт
копии трёх новых тестов V4 для сверки независимым проверяющим
(например, `cmp tests/test_v4_safety_build.py candidate/test_v4_safety_build.py`).

Запуск — из `candidate` (см. LAPTOP_TEST_RUNBOOK_RU.md §7):

```powershell
cd candidate
python -m pytest -q
```

| Файл | Тестов | Назначение |
|---|---|---|
| test_v4_order_ledger_first_append.py | 17 | P1-контракт первой записи реестра (ТЗ V4 §2) |
| test_v4_safety_build.py | 18 | режимы сборки, guard заявок, fail-closed (ТЗ V4 §7/§8) |
| test_v4_integration_integrity.py | 8 | группы 22/24 интеграционного аудита (ТЗ V4 §4) |
