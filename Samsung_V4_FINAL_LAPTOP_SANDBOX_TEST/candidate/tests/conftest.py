# tests/conftest.py — CORRECTIVE AUDIT V3 (ТЗ §5.15, тестовая инфраструктура).
#
# Причина появления: subprocess-скрипты tests/test_persistence.py и
# корневого test_persistence.py импортируют `import tests.conftest` +
# `from tests.conftest import _install_stubs`, но файл tests/conftest.py
# в дереве ОТСУТСТВОВАЛ — SDK-заглушки жили только в корневом conftest.py
# (шапка которого при этом самоидентифицируется как «tests/conftest.py»).
# В результате оба subprocess-теста persistence падали с
# ModuleNotFoundError('t_tech') вне зависимости от тестируемой логики
# сохранения/восстановления state.json.
#
# Исправление: шим реэкспортирует установщик заглушек из корневого
# conftest.py — единственного источника истины по заглушкам; дублирование
# логики не создаётся. Утверждения тестов не меняются, изоляция
# _isolate_main_globals (autouse) продолжает определяться корневым
# conftest и применяется pytest'ом ко всем подкаталогам как прежде.
#
# Идемпотентность: _install_stubs() ставит заглушки через
# sys.modules.setdefault — повторные вызовы безопасны (проверено на
# subprocess-прогонах V3).
from conftest import _install_stubs  # noqa: F401
