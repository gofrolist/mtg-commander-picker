import tomllib
from pathlib import Path

pyproject = tomllib.loads(Path("pyproject.toml").read_text())
deps = pyproject["project"]["dependencies"]

# Strip parentheses and print
for dep in deps:
    package = dep.split()[0]  # "flask (>=3.1.0,<4.0.0)" -> "flask"
    print(package)


