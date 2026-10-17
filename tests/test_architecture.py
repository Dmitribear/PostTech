import ast
from pathlib import Path

import pytest
from httpx import ConnectError
from postgrest.exceptions import APIError
from unittest.mock import Mock

from app.domain.errors import StorageError, StorageUnavailable
from app.infrastructure.database.gateway import SupabaseQuery

APP = Path(__file__).resolve().parents[1] / "app"


def test_inner_layers_do_not_depend_on_frameworks_or_adapters():
    forbidden = {"fastapi", "starlette", "httpx", "postgrest", "supabase"}
    violations = []
    for layer in ("domain", "application"):
        for path in (APP / layer).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                modules = (
                    [node.module or ""]
                    if isinstance(node, ast.ImportFrom)
                    else [n.name for n in node.names]
                    if isinstance(node, ast.Import)
                    else []
                )
                for module in modules:
                    outer = (
                        "app.infrastructure",
                        "app.presentation",
                        "app.bootstrap",
                        "app.main",
                    )
                    if layer == "domain":
                        outer += ("app.application",)
                    if module.split(".")[0] in forbidden or module.startswith(outer):
                        violations.append(
                            f"{path.relative_to(APP)}:{node.lineno}: {module}"
                        )
    assert not violations, "\n".join(violations)


@pytest.mark.parametrize(
    "upstream,expected",
    [
        (ConnectError("transport detail"), StorageUnavailable),
        (
            APIError(
                {"code": "PT409", "message": "conflict", "hint": None, "details": None}
            ),
            StorageError,
        ),
    ],
)
def test_gateway_translates_external_errors(upstream, expected):
    query = Mock()
    query.execute.side_effect = upstream
    with pytest.raises(expected):
        SupabaseQuery(query).execute()
