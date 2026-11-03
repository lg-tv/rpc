#!/usr/bin/env python3
"""Ставит и обновляет Python-пакеты из подпапок git-репозитория вики.

Все пакеты лежат в одном репозитории, поэтому коммит у них общий. Скрипт берёт
HEAD удалённой ветки, сравнивает его с коммитом, который pip записал в
direct_url.json при установке каждого пакета, и переустанавливает только
отставшие. Каждый пакет ставится отдельным дистрибутивом (pip install на свою
подпапку), поэтому импортируются они независимо.

Запуск (одинаково на Windows и Linux):

    .venv\\Scripts\\python.exe scripts\\update_module.py    # Windows
    .venv/bin/python scripts/update_module.py              # Linux/macOS

Ключи:
    --check       только проверить, есть ли обновления (код выхода 1 = есть)
    --force       переустановить все пакеты, даже если коммиты совпадают
    --only NAME   обновить только один пакет (mywikimodule или wikistats)
    --ref R       ветка, тег или хеш (по умолчанию master)
    --repo URL    другой адрес репозитория (например, file:///... чтобы
                  проверить локальные коммиты до пуша)
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

REPO = "https://github.com/lg-tv/rpc.wiki.git"
DEFAULT_REF = "master"

# Единый список того, что ставим: пакет, модуль для импорта и подпапка в репозитории.
PACKAGES = (
    {"dist": "mywikimodule", "module": "mywikimodule", "subdir": "sub1"},
    {"dist": "wikistats", "module": "wikistats", "subdir": "sub2"},
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def die(message, code=2):
    print("ошибка: " + message, file=sys.stderr)
    raise SystemExit(code)


def ensure_venv():
    """Перезапускает скрипт через .venv, если есть .venv, а мы запущены не из него."""
    if sys.prefix != sys.base_prefix:
        return
    for python in (
        PROJECT_ROOT / ".venv" / "Scripts" / "python.exe",
        PROJECT_ROOT / ".venv" / "bin" / "python",
    ):
        if python.exists():
            print("перезапуск через " + str(python), flush=True)
            raise SystemExit(subprocess.run([str(python), *sys.argv]).returncode)


def git_env():
    # Без интерактивного запроса пароля: при недоступном репозитории лучше упасть сразу.
    return dict(os.environ, GIT_TERMINAL_PROMPT="0")


def is_hex(ref):
    return 7 <= len(ref) <= 40 and all(c in "0123456789abcdef" for c in ref.lower())


def same(a, b):
    """Сравнивает хеши, допуская сокращённую запись любого из них."""
    if not a or not b:
        return False
    n = min(len(a), len(b))
    return a[:n].lower() == b[:n].lower()


def resolve_remote(repo, ref):
    """Хеш коммита, на который указывает ref в удалённом репозитории."""
    # Хеш коммита: ls-remote ищет только по именам ссылок, поэтому берём как есть.
    if is_hex(ref):
        return ref.lower()

    proc = subprocess.run(
        ["git", "ls-remote", repo, ref],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        env=git_env(),
    )
    if proc.returncode != 0:
        die("git ls-remote: " + (proc.stderr or proc.stdout).strip())

    rows = [line.split("\t") for line in proc.stdout.splitlines() if line.strip()]
    if not rows:
        die("в " + repo + " нет ссылки " + repr(ref))

    # У аннотированного тега ls-remote отдаёт тег и распакованный коммит (^{}).
    peeled = [sha for sha, name in rows if name.endswith("^{}")]
    return (peeled or [sha for sha, _ in rows])[0].lower()


def installed_commit(pkg):
    """Коммит установленной копии пакета или None, если её нет/она не из git."""
    spec = find_spec(pkg["module"])
    if spec is None or not spec.origin:
        return None
    for meta in Path(spec.origin).parent.glob(pkg["dist"] + "-*.dist-info/direct_url.json"):
        try:
            info = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        vcs = info.get("vcs_info") or {}
        if info.get("subdirectory") == pkg["subdir"] and vcs.get("commit_id"):
            return vcs["commit_id"].lower()
    return None


def import_ok(module):
    """Проверяет в отдельном процессе, что модуль действительно импортируется."""
    proc = subprocess.run(
        [sys.executable, "-c", "import " + module],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    detail = (proc.stderr or "").strip().splitlines()
    return proc.returncode == 0, (detail[-1] if detail else "")


def install(repo, pkg, target):
    """Ставит пакет, зафиксированный на конкретном коммите. Возвращает True при успехе."""
    spec = "git+" + repo + "@" + target + "#subdirectory=" + pkg["subdir"]
    print("  pip install " + spec, flush=True)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--force-reinstall",
            "--no-cache-dir",
            spec,
        ]
    )
    return proc.returncode == 0


def short(commit):
    return commit[:7] if commit else "нет"


def main():
    parser = argparse.ArgumentParser(description="Обновление пакетов из git.")
    parser.add_argument("--ref", default=DEFAULT_REF, help="ветка, тег или хеш")
    parser.add_argument("--repo", default=REPO, help="адрес git-репозитория")
    parser.add_argument("--only", help="обновить только пакет с таким именем")
    parser.add_argument("--check", action="store_true", help="только проверить")
    parser.add_argument("--force", action="store_true", help="переустановить всегда")
    args = parser.parse_args()

    packages = [p for p in PACKAGES if not args.only or p["dist"].lower() == args.only.lower()]
    if not packages:
        die("неизвестный пакет " + repr(args.only) + "; доступны: " +
            ", ".join(p["dist"] for p in PACKAGES))

    if shutil.which("git") is None:
        die("git не найден в PATH - pip не сможет клонировать репозиторий")

    target = resolve_remote(args.repo, args.ref)
    print("репозиторий: " + args.repo + " (" + args.ref + ") -> " + target[:7])

    updated, current_count, stale, failed = 0, 0, 0, 0

    for pkg in packages:
        label = pkg["dist"] + " (" + pkg["subdir"] + ")"
        current = installed_commit(pkg)

        if same(current, target) and not args.force:
            ok, err = import_ok(pkg["module"])
            if ok:
                print(label + ": " + short(current) + " - актуален")
                current_count += 1
            else:
                print(label + ": " + short(current) + " - не импортируется: " + err, file=sys.stderr)
                failed += 1
            continue

        if args.check:
            print(label + ": " + short(current) + " -> " + short(target) + " - требуется обновление")
            stale += 1
            continue

        print(label + ": " + short(current) + " -> " + short(target) + " - обновляю")
        if not install(args.repo, pkg, target):
            print(label + ": pip install завершился с ошибкой", file=sys.stderr)
            failed += 1
            continue

        actual = installed_commit(pkg)
        if not same(actual, target):
            print(label + ": после установки " + short(actual) + ", ожидался " + short(target),
                  file=sys.stderr)
            failed += 1
            continue

        ok, err = import_ok(pkg["module"])
        if not ok:
            print(label + ": установлен, но не импортируется: " + err, file=sys.stderr)
            failed += 1
            continue

        print(label + ": " + short(actual) + " - установлен")
        updated += 1

    print("итог: актуально " + str(current_count) + ", обновлено " + str(updated) +
          ", ошибок " + str(failed) + (", к обновлению " + str(stale) if args.check else ""))

    return 1 if failed or (args.check and stale) else 0


if __name__ == "__main__":
    # Строки не должны перемешиваться с выводом pip при перенаправлении в файл/пайп.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    ensure_venv()
    raise SystemExit(main())
