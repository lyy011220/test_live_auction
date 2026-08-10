"""用例追溯: 记录本次已导入用例，并可从源码发现完整用例目录。"""
import ast
import os
import re
from collections import OrderedDict
from pathlib import Path
from typing import Mapping

CASES: "OrderedDict[str, dict]" = OrderedDict()

_CASE_RE = re.compile(r"^(?P<domain>[A-Z]+)-(?P<type>[A-Z]+)-(?P<num>\d+)$")


def case(case_id: str):
    """登记用例 ID, 自动解析域/类型, 并据是否带 skip 标记判定 implemented/stub。"""
    def deco(func):
        existing = CASES.get(case_id)
        current = f"{func.__module__}.{func.__name__}"
        if existing is not None:
            previous = f"{existing['module']}.{existing['func']}"
            raise ValueError(f"重复 Case ID {case_id}: {previous} 与 {current}")
        m = _CASE_RE.match(case_id)
        domain = m.group("domain") if m else "?"
        ctype = m.group("type") if m else "?"
        status = "implemented"
        for mark in getattr(func, "pytestmark", []) or []:
            if getattr(mark, "name", "") == "skip":
                status = "stub"
                break
        CASES[case_id] = {
            "domain": domain,
            "type": ctype,
            "func": func.__name__,
            "module": func.__module__,
            "status": status,
        }
        func.__allure_case_id__ = case_id
        return func
    return deco


def _decorator_name(node: ast.expr) -> str:
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    if isinstance(node, ast.Attribute):
        parent = _decorator_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def discover_cases(test_root: str | Path) -> "OrderedDict[str, dict]":
    """静态扫描 tests/test_*.py，生成不受本次 pytest 选择范围影响的完整目录。"""
    root = Path(test_root).resolve()
    discovered: "OrderedDict[str, dict]" = OrderedDict()
    for source in sorted(root.rglob("test_*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8-sig"), filename=str(source))
        module = ".".join(source.relative_to(root.parent).with_suffix("").parts)
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            case_id = None
            status = "implemented"
            for decorator in node.decorator_list:
                name = _decorator_name(decorator)
                if name.endswith(".skip") or name.endswith(".skipif"):
                    status = "stub"
                if name == "case" and isinstance(decorator, ast.Call) and decorator.args:
                    value = decorator.args[0]
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        case_id = value.value
            if not case_id:
                continue
            match = _CASE_RE.match(case_id)
            if case_id in discovered:
                previous = discovered[case_id]
                raise ValueError(
                    f"重复 Case ID {case_id}: "
                    f"{previous['module']}.{previous['func']} 与 {module}.{node.name}"
                )
            discovered[case_id] = {
                "domain": match.group("domain") if match else "?",
                "type": match.group("type") if match else "?",
                "func": node.name,
                "module": module,
                "status": status,
            }
    return discovered


def dump_traceability(
    path: str | Path = "reports/traceability.md",
    cases: Mapping[str, dict] | None = None,
    title: str = "用例追溯矩阵",
) -> None:
    selected = cases if cases is not None else CASES
    path = Path(path)
    os.makedirs(path.parent, exist_ok=True)
    lines = [
        f"# {title}",
        "",
        "| Case ID | 域 | 类型 | 测试函数 | 模块 | 状态 |",
        "|---|---|---|---|---|---|",
    ]
    for cid, info in selected.items():
        lines.append(
            f"| {cid} | {info['domain']} | {info['type']} | {info['func']} | {info['module']} | {info['status']} |"
        )
    implemented = sum(1 for i in selected.values() if i["status"] == "implemented")
    stub = sum(1 for i in selected.values() if i["status"] == "stub")
    lines.append("")
    lines.append(f"共 {len(selected)} 个 Case ID (implemented={implemented}, stub={stub})")
    path.write_text("\n".join(lines), encoding="utf-8")
