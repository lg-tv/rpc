#!/usr/bin/env python3
"""Ставит/обновляет mywikimodule из git-репозитория вики в виртуальное окружение.

Скрипт берёт коммит, установленный сейчас (из direct_url.json, который pip
создаёт при установке из git), сравнивает его с коммитом в удалённой ветке и
переустанавливает пакет, только если они различаются. Если скрипт запущен не из
виртуального окружения, а рядом есть .venv, он перезапускается через его python.

Запуск (одинаково на Windows и Linux):

    .venv\\Scripts\\python.exe scripts\\update_module.py   # Windows
    .venv/bin/python scripts/update_module.py             # Linux/macOS

Ключи:
    --check   только проверить, есть ли обновление (код выхода 1 = есть)
    --force   переустановить, даже если коммит совпадает
    --ref R   ветка, тег или хеш (по умолчанию master)
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

PACKAGE = "mywikimodule"
REPO = "https://github.com/lg-tv/rpc.wiki.git"
SUBDIR = "sub1"
DEFAULT_REF = "master"

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
    return dict(os.environ, GIT_TERMINAL_PROMPT="0")


def is_hex(ref):
    return 7 <= len(ref) <= 40 and all(c in "0123456789abcdef" for c in ref.lower())


def same(a, b):
    """Сравнивает хеши, допуская сокращённую запись любого из них."""
    if not a or not b:
        return False
    return a[: min(len(a), len(b))].lower() == b[: min(len(a), len(b))].lower()


def resolve_remote(ref):
    """Возвращает хеш коммита, на который указывает ref в удалённом репозитории."""
    # Хеш коммита: ls-remote ищет только по именам ссылок, поэтому берём как есть.
    if is_hex(ref):
        return ref.lower()

    proc = subprocess.run(
        ["git", "ls-remote", REPO, ref],
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
        die("в " + REPO + " нет ссылки " + repr(ref))

    # У аннотированного тега ls-remote отдаёт тег и распакованный коммит (^{}).
    peeled = [sha for sha, name in rows if name.endswith("^{}")]
    return (peeled or [sha for sha, _ in rows])[0].lower()


def installed_commit():
    """Коммит установленной копии или None, если она не из этого git-репозитория."""
    spec = find_spec(PACKAGE)
    if spec is None or not spec.origin:
        return None
    for meta in Path(spec.origin).parent.glob(PACKAGE + "-*.dist-info/direct_url.json"):
        try:
            info = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        vcs = info.get("vcs_info") or {}
        if info.get("subdirectory") == SUBDIR and vcs.get("commit_id"):
            return vcs["commit_id"].lower()
    return None


def short(commit):
    return commit[:7] if commit else "нет (не установлен или установлен не из git)"


def main():
    parser = argparse.ArgumentParser(description="Обновление " + PACKAGE + " из git.")
    parser.add_argument("--ref", default=DEFAULT_REF, help="ветка, тег или хеш")
    parser.add_argument("--check", action="store_true", help="только проверить")
    parser.add_argument("--force", action="store_true", help="переустановить всегда")
    args = parser.parse_args()

    if shutil.which("git") is None:
        die("git не найден в PATH - pip не сможет клонировать репозиторий")

    target = resolve_remote(args.ref)
    current = installed_commit()

    print("установлено: " + short(current))
    print("в git      : " + short(target) + " (" + args.ref + ")")

    if same(current, target) and not args.force:
        print("обновление не требуется")
        return 0

    if args.check:
        print("доступен новый коммит")
        return 1

    spec = "git+" + REPO + "@" + target + "#subdirectory=" + SUBDIR
    print("устанавливаю " + PACKAGE + " @ " + target[:7] + " ...")
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
    if proc.returncode != 0:
        die("pip install завершился с ошибкой", code=proc.returncode)

    actual = installed_commit()
    if not same(actual, target):
        die("после установки коммит " + short(actual) + ", ожидался " + short(target), code=1)

    print("готово: " + PACKAGE + " @ " + actual[:7] + " в " + sys.prefix)
    return 0


if __name__ == "__main__":
    # Строки не должны перемешиваться с выводом pip при перенаправлении в файл/пайп.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    ensure_venv()
    raise SystemExit(main())
