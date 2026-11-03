"""Guard dependency boundaries of the business modular backend."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.append(node.module)
    return result


@pytest.mark.parametrize(
    ("source", "forbidden"),
    [
        (
            "backend/domain",
            (
                "backend.application",
                "backend.infrastructure",
                "backend.presentation",
                "sqlalchemy",
                "fastapi",
            ),
        ),
        (
            "backend/application",
            ("backend.infrastructure", "backend.presentation", "sqlalchemy", "fastapi"),
        ),
        (
            "backend/presentation/api/routers",
            ("backend.infrastructure", "sqlalchemy"),
        ),
        (
            "backend/worker.py",
            (
                "backend.infrastructure.database.models",
                "backend.infrastructure.database.repositories",
                "sqlalchemy",
            ),
        ),
    ],
)
def test_dependency_direction(source: str, forbidden: tuple[str, ...]):
    boundary = ROOT / source
    assert boundary.exists(), f"Missing architecture boundary: {source}"
    files = [boundary] if boundary.is_file() else sorted(boundary.rglob("*.py"))
    violations = [
        f"{path.relative_to(ROOT)} imports {module}"
        for path in files
        for module in imported_modules(path)
        if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden)
    ]
    assert not violations, "\n".join(violations)
