"""Tests for ToolRegistry — storage, retrieval, duplicate rejection."""

import pytest
from pydantic import BaseModel

from marionette.gateway import Tool, ToolRegistry


class _DummyArgs(BaseModel):
    x: str


class _DummyResult(BaseModel):
    y: str


class _DummyTool(Tool[_DummyArgs, _DummyResult]):
    name = "dummy"
    description = "test tool"
    args_schema = _DummyArgs
    result_schema = _DummyResult

    def run(self, args: _DummyArgs) -> _DummyResult:
        return _DummyResult(y=args.x)


def test_empty_registry_has_no_tools() -> None:
    """A fresh registry is empty."""
    reg = ToolRegistry()
    assert len(reg) == 0
    assert reg.names() == []


def test_register_adds_tool() -> None:
    """Registering a tool makes it findable."""
    reg = ToolRegistry()
    reg.register(_DummyTool())
    assert len(reg) == 1
    assert "dummy" in reg
    assert reg.names() == ["dummy"]


def test_lookup_returns_registered_tool() -> None:
    """Lookup returns the tool instance for a known name."""
    reg = ToolRegistry()
    tool = _DummyTool()
    reg.register(tool)
    assert reg.lookup("dummy") is tool


def test_lookup_returns_none_for_unknown() -> None:
    """Lookup returns None for an unregistered name — no exception."""
    reg = ToolRegistry()
    assert reg.lookup("nonexistent") is None


def test_duplicate_registration_raises() -> None:
    """Registering two tools with the same name raises ValueError."""
    reg = ToolRegistry()
    reg.register(_DummyTool())
    with pytest.raises(ValueError, match="already registered"):
        reg.register(_DummyTool())


def test_abstract_tool_cannot_be_instantiated() -> None:
    """The Tool base class is abstract and cannot be constructed directly."""
    with pytest.raises(TypeError):
        Tool()  # type: ignore[abstract]
