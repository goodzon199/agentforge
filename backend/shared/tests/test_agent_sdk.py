from __future__ import annotations

from typing import ClassVar

from shared.agents import (
    Agent,
    AgentContext,
    AgentOutput,
    AgentRegistry,
    run_agent,
)
from shared.tools import Tool, ToolRegistry, ToolResult


class GreetAgent(Agent):
    kind = "greet"
    name = "greet-agent"
    description = "Says hello."
    permissions: ClassVar[list[str]] = ["customer.read"]
    tools: ClassVar[list[str]] = ["echo"]

    def execute(self, ctx: AgentContext) -> AgentOutput:
        if ctx.memory is not None:
            ctx.memory.remember("greeted")
        output = ctx.tools.run("echo", text="hi") if ctx.tools else ToolResult(ok=False)
        return AgentOutput(
            response=f"hello {ctx.input_data.get('who', 'world')}",
            data={"tool_ok": output.ok},
        )


class AsyncAgent(Agent):
    kind = "async_greet"

    async def execute(self, ctx: AgentContext) -> AgentOutput:
        return AgentOutput(response="async done")


class Memory:
    def __init__(self) -> None:
        self.items: list[str] = []

    def remember(self, content: str, kind: str = "interaction") -> None:
        self.items.append(content)

    def learn(self, content: str, source_task_id=None) -> None:
        self.items.append(content)

    def recall(self) -> dict:
        return {"items": self.items}

    def search(self, query: str) -> list:
        return []


class EchoTool(Tool):
    name = "echo"
    description = "Echoes text."
    permissions: ClassVar[list[str]] = []

    def run(self, **kwargs) -> ToolResult:
        return ToolResult(ok=True, data={"text": kwargs.get("text", "")})


def _registry() -> AgentRegistry:
    registry = AgentRegistry()
    registry.register(GreetAgent)
    registry.register(AsyncAgent)
    return registry


def test_registry_describe():
    registry = _registry()
    assert set(registry.kinds()) == {"greet", "async_greet"}
    info = registry.get("greet").describe()
    assert info["kind"] == "greet"
    assert info["permissions"] == ["customer.read"]
    assert info["tools"] == ["echo"]


def test_run_agent_with_context():
    registry = _registry()
    tools = ToolRegistry()
    tools.register(EchoTool())
    ctx = AgentContext(
        objective="say hi",
        input_data={"who": "Мария"},
        agent_id="a-1",
        memory=Memory(),
        tools=tools,
    )
    agent = registry.require("greet")()
    output = run_agent(agent, ctx)
    assert output.response == "hello Мария"
    assert output.data["tool_ok"] is True
    assert agent.ctx is ctx


def test_run_agent_supports_async():
    registry = _registry()
    ctx = AgentContext(objective="x")
    output = run_agent(registry.require("async_greet")(), ctx)
    assert output.response == "async done"


def test_missing_permission_facade_is_noop():
    registry = _registry()
    ctx = AgentContext(objective="x", input_data={"who": "x"})
    agent = registry.require("greet")()
    output = run_agent(agent, ctx)
    assert output.response == "hello x"


def test_unknown_kind_raises():
    registry = _registry()
    try:
        registry.require("nope")
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError")


def test_tool_registry():
    tools = ToolRegistry()
    tools.register(EchoTool())
    assert tools.names() == ["echo"]
    assert tools.list()[0]["name"] == "echo"
    assert tools.run("echo", text="y").ok is True
    assert tools.run("missing").ok is False
