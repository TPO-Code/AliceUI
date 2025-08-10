# backend/alice/tools_lib/code_analyzer_tools.py
import ast
import json
from pathlib import Path
from typing import Any, Dict, Set

# --- Local Imports ---
# We use the same secure path resolver as your other tools
from ._base import _resolve_and_validate_path


# --- Helper Functions (Extracted from the original CodeAnalyzerServer class) ---
# These are the core logic functions, now acting as internal helpers.

def _analyze_structure(tree: ast.AST) -> Dict[str, Any]:
    functions = []
    classes = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            # Exclude methods inside classes from the top-level functions list
            if not any(isinstance(p, ast.ClassDef) for p in getattr(node, 'parent_path', [])):
                functions.append({
                    'name': node.name,
                    'arguments': [arg.arg for arg in node.args.args],
                    'line_number': node.lineno
                })
        elif isinstance(node, ast.ClassDef):
            # Find methods specifically for this class
            methods = []
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    methods.append(item.name)

            classes.append({
                'name': node.name,
                'methods': methods,
                'line_number': node.lineno
            })

    # Add parent references to the tree for more accurate analysis
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child.parent_path = getattr(node, 'parent_path', []) + [node]

    return {
        "type": "structure",
        "functions": functions,
        "classes": classes
    }


def _get_complexity_level(complexity: int) -> str:
    if complexity <= 5:
        return "low"
    elif complexity <= 10:
        return "moderate"
    else:
        return "high"


def _get_variable_usage(node: ast.AST) -> Set[str]:
    variables = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            variables.add(n.id)
    return variables


def _analyze_complexity(tree: ast.AST) -> Dict[str, Any]:
    complexity_info = {}

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Count decision points for cyclomatic complexity
            decisions = [n for n in ast.walk(node) if isinstance(n, (
                ast.If, ast.For, ast.While, ast.And, ast.Or, ast.ExceptHandler
            ))]

            cyclomatic_complexity = len(decisions) + 1

            complexity_info[node.name] = {
                'cyclomatic_complexity': cyclomatic_complexity,
                'complexity_level': _get_complexity_level(cyclomatic_complexity),
                'decision_points': len(decisions),
                'line_count': (node.end_lineno - node.lineno + 1) if hasattr(node, 'end_lineno') else 1,
                'variables_defined': list(_get_variable_usage(node))
            }

    total_complexity = sum(f['cyclomatic_complexity'] for f in complexity_info.values())

    return {
        "type": "complexity",
        "functions": complexity_info,
        "summary": {
            "total_functions": len(complexity_info),
            "average_complexity": total_complexity / len(complexity_info) if complexity_info else 0,
            "most_complex_function": max(complexity_info.items(), key=lambda x: x[1]['cyclomatic_complexity'])[
                0] if complexity_info else None
        }
    }


def _analyze_dependencies(tree: ast.AST) -> Dict[str, Any]:
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            # For "from package import module", we care about "package"
            if node.module:
                imports.add(node.module.split('.')[0])

    return {
        "type": "dependencies",
        "imports": sorted(list(imports))
    }


# --- Main Tool Function ---

def analyze_python_code(file_path: str, analysis_type: str) -> str:
    """
    Performs static analysis on a single Python file in the secure I/O directory.
    - 'structure': Shows classes, methods, and functions.
    - 'complexity': Calculates cyclomatic complexity for each function.
    - 'dependencies': Lists all imported modules.
    """
    print(f"--- [Alice/CodeAnalyzer] --- Analyzing '{file_path}' for '{analysis_type}'")

    # Use your existing security pattern to resolve and validate the path
    safe_path_str = _resolve_and_validate_path(file_path)
    if not safe_path_str:
        return f"Error: The path '{file_path}' is invalid or outside the allowed directory."

    path = Path(safe_path_str)

    if not path.exists():
        return f"Error: File not found: {file_path}"
    if not path.is_file() or path.suffix != '.py':
        return f"Error: Path must point to a Python (.py) file."

    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()

        tree = ast.parse(content)

        if analysis_type == 'structure':
            result = _analyze_structure(tree)
        elif analysis_type == 'complexity':
            result = _analyze_complexity(tree)
        elif analysis_type == 'dependencies':
            result = _analyze_dependencies(tree)
        else:
            return f"Error: Unknown analysis type: '{analysis_type}'. Must be 'structure', 'complexity', or 'dependencies'."

        # Return the result as a nicely formatted JSON string, just like your other tools
        return json.dumps(result, indent=2)

    except SyntaxError as e:
        return f"Error: Could not parse the Python file. It contains a syntax error on line {e.lineno}."
    except Exception as e:
        return f"An unexpected error occurred during analysis: {str(e)}"


def get_mapping():
    return {
        "python.analyze_code": analyze_python_code,
    }