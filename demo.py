"""Демо: состояние модуля mywikimodule, установленного через pip из git.

Запуск:  .venv\\Scripts\\python.exe demo.py
"""

import json
from importlib.metadata import distribution, version

import mywikimodule
from mywikimodule import WikiCalculator, hello_from_wiki

direct_url = distribution("mywikimodule").read_text("direct_url.json")
commit = json.loads(direct_url)["vcs_info"]["commit_id"][:7] if direct_url else "unknown"

report = " | ".join([
    f"mywikimodule {version('mywikimodule')} @ {commit}",
    f"path={mywikimodule.__file__}",
    f"add(2, 3)={WikiCalculator().add(2, 3)}",
    f"hello={hello_from_wiki()}",
])
print(report)
