"""Workflow SDK (sprint 5.3): declarative business processes shipped by packs.

A workflow is a DAG of nodes. Each node is one of:

- ``agent``   — run an agent (by type; resolved through the pack registry)
- ``condition`` — evaluate a boolean expression over the run context and branch
- ``human``   — pause: hand the run to a human (approval gate), resumable
- ``end``     — terminal node (final result / fallback branch)

Packs declare workflows in their manifest and ship the definitions as YAML.
Core loads them over the internal contract and executes them; the workflow
runtime lives in core and dispatches agent nodes to whichever pack provides
the agent. Pure SDK (pydantic + yaml, no SQLAlchemy/FastAPI).
"""

from __future__ import annotations

import ast
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator

WORKFLOW_FILENAME = "workflow.yaml"


class NodeType(str, Enum):
    agent = "agent"
    condition = "condition"
    human = "human"
    end = "end"


class WorkflowNode(BaseModel):
    """One node in a workflow DAG."""

    id: str = Field(min_length=1, max_length=80)
    type: NodeType

    # agent / condition
    agent: str | None = None
    expression: str | None = None  # boolean expression for condition nodes
    branches: dict[str, str] = Field(default_factory=dict)  # true/false -> node id

    # edges
    next: str | None = None

    # human
    message: str = ""
    priority: str = "normal"

    # metadata
    description: str = ""


class Workflow(BaseModel):
    """A declarative business process (DAG of nodes)."""

    name: str = Field(min_length=1, max_length=80)
    version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    start: str = Field(min_length=1)
    nodes: list[WorkflowNode] = Field(min_length=1)

    def node(self, node_id: str) -> WorkflowNode | None:
        return next((n for n in self.nodes if n.id == node_id), None)

    @model_validator(mode="after")
    def _validate(self) -> Workflow:
        validate_workflow(self)
        return self


class WorkflowError(ValueError):
    """Raised when a workflow cannot be parsed or fails validation."""


def parse_workflow(data: str | bytes | dict) -> Workflow:
    try:
        raw = yaml.safe_load(data) if isinstance(data, (str, bytes)) else data
    except yaml.YAMLError as exc:
        raise WorkflowError(f"workflow.yaml не валидный YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise WorkflowError("workflow должен быть отображением (YAML map).")
    try:
        return Workflow.model_validate(raw)
    except ValidationError as exc:
        raise WorkflowError(f"workflow не проходит схему: {exc}") from exc


def load_workflow(path: str | Path) -> Workflow:
    file_path = Path(path)
    if not file_path.is_file():
        raise WorkflowError(f"workflow не найден: {file_path}")
    return parse_workflow(file_path.read_text(encoding="utf-8"))


def validate_workflow(workflow: Workflow) -> None:
    ids = [n.id for n in workflow.nodes]
    if len(ids) != len(set(ids)):
        raise WorkflowError("nodes: id не уникальны.")
    if workflow.start not in ids:
        raise WorkflowError(f"start {workflow.start!r} не существует.")

    for node in workflow.nodes:
        if node.type == NodeType.agent and not node.agent:
            raise WorkflowError(f"node {node.id!r}: agent node без поля agent.")
        if node.type == NodeType.condition:
            if not node.expression:
                raise WorkflowError(f"node {node.id!r}: condition без expression.")
            if set(node.branches) != {"true", "false"}:
                raise WorkflowError(
                    f"node {node.id!r}: condition branches должны быть true/false."
                )
        for target in list(node.branches.values()) + ([node.next] if node.next else []):
            if target not in ids:
                raise WorkflowError(
                    f"node {node.id!r}: переход на несуществующий {target!r}."
                )
        if node.type == NodeType.end and (node.next or node.branches):
            raise WorkflowError(f"node {node.id!r}: end node не может иметь переходы.")


# --- Safe condition evaluator ----------------------------------------------

class ConditionError(ValueError):
    """Raised when a condition expression cannot be parsed/evaluated."""


_ALLOWED_BINOPS = frozenset({ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod})
_ALLOWED_COMPARES = frozenset(
    {
        ast.Eq,
        ast.NotEq,
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
        ast.In,
        ast.NotIn,
    }
)
_ALLOWED_UNARY = frozenset({ast.Not, ast.USub})
_ALLOWED_BOOL = frozenset({ast.And, ast.Or})


def evaluate_condition(expression: str, context: dict[str, Any]) -> bool:
    """Evaluate a restricted boolean expression against ``context``.

    Supports dotted attribute access, string/number/bool/list indexing and
    comparisons. No calls, no attribute mutation — safe for untrusted input.
    """
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ConditionError(f"condition не парсится: {expression!r}") from exc
    return bool(_Eval(expression, context).visit(tree.body))


class _Eval(ast.NodeVisitor):
    def __init__(self, expression: str, context: dict[str, Any]) -> None:
        self._expression = expression
        self._context = context

    def _get(self, obj: Any, name: str) -> Any:
        if isinstance(obj, dict):
            return obj.get(name)
        return getattr(obj, name, None)

    def visit_Expression(self, node):
        return self.visit(node.body)

    def visit_BoolOp(self, node):
        if type(node.op) not in _ALLOWED_BOOL:
            raise ConditionError(f"недопустимая операция в {self._expression!r}")
        if type(node.op) is ast.And:
            return all(self.visit(v) for v in node.values)
        return any(self.visit(v) for v in node.values)

    def visit_BinOp(self, node):
        if type(node.op) not in _ALLOWED_BINOPS:
            raise ConditionError(f"недопустимая операция в {self._expression!r}")
        left = self.visit(node.left)
        right = self.visit(node.right)
        op = node.op
        if type(op) is ast.Add:
            return left + right
        if type(op) is ast.Sub:
            return left - right
        if type(op) is ast.Mult:
            return left * right
        if type(op) is ast.Div:
            return left / right
        return left % right

    def visit_Compare(self, node):
        if type(node.ops[0]) not in _ALLOWED_COMPARES:
            raise ConditionError(f"недопустимое сравнение в {self._expression!r}")
        left = self.visit(node.left)
        for op, comparator in zip(node.ops, node.comparators, strict=False):
            right = self.visit(comparator)
            if type(op) is ast.Eq and left != right:
                return False
            if type(op) is ast.NotEq and left == right:
                return False
            if type(op) is ast.Lt and not (left < right):
                return False
            if type(op) is ast.LtE and not (left <= right):
                return False
            if type(op) is ast.Gt and not (left > right):
                return False
            if type(op) is ast.GtE and not (left >= right):
                return False
            if type(op) is ast.In and left not in right:
                return False
            if type(op) is ast.NotIn and left in right:
                return False
        return True

    def visit_UnaryOp(self, node):
        if type(node.op) not in _ALLOWED_UNARY:
            raise ConditionError(f"недопустимая унарная операция в {self._expression!r}")
        operand = self.visit(node.operand)
        if type(node.op) is ast.Not:
            return not operand
        return -operand

    def visit_Name(self, node):
        if node.id == "context":
            return self._context
        if node.id not in self._context:
            raise ConditionError(f"неизвестная переменная {node.id!r}")
        return self._context[node.id]

    def visit_Attribute(self, node):
        return self._get(self.visit(node.value), node.attr)

    def visit_Call(self, node):
        """Allow only ``dict.get(key, default)`` (context lookups)."""
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "get":
            raise ConditionError(f"вызовы запрещены в {self._expression!r}")
        callee = self.visit(node.func.value)
        if not isinstance(callee, dict) or len(node.args) not in (1, 2):
            raise ConditionError(f"недопустимый get() в {self._expression!r}")
        key = self.visit(node.args[0])
        default = self.visit(node.args[1]) if len(node.args) == 2 else None
        return callee.get(key, default)

    def visit_Subscript(self, node):
        return self.visit(node.value)[self.visit(node.slice)]

    def visit_Constant(self, node):
        return node.value

    def visit_List(self, node):
        return [self.visit(e) for e in node.elts]

    def visit_Tuple(self, node):
        return tuple(self.visit(e) for e in node.elts)

    def visit_Dict(self, node):
        return {
            self.visit(k): self.visit(v)
            for k, v in zip(node.keys, node.values, strict=False)
        }

    def visit_Slice(self, node):
        return slice(
            self.visit(node.lower) if node.lower else None,
            self.visit(node.upper) if node.upper else None,
            self.visit(node.step) if node.step else None,
        )

    def generic_visit(self, node):
        raise ConditionError(f"недопустимое выражение в {self._expression!r}")
