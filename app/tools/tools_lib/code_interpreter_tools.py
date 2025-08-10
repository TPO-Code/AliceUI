# backend/alice/tools_lib/code_interpreter_tools.py
import io
import os
import sys
import traceback
from contextlib import redirect_stdout
import builtins
# Note: For a production system, this should be executed in a more secure sandbox,
# such as a Docker container or a dedicated virtual machine, to prevent
# malicious code from affecting the host system.
# The `restricted_globals` dictionary is a basic security measure.
# Ensure no dangerous libraries (e.g., os, subprocess) are available by default.
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# --- Local Imports ---
from ._base import FILE_IO_DIR, _resolve_and_validate_path
from .system_tools import execute_shell_command


def _execute_sandboxed_code(code: str) -> str:
    """Internal function to execute code in a restricted environment."""
    # A basic sandbox: define what globals are available to the executed code.
    restricted_globals = {
        "__builtins__": {k: v for k, v in builtins.__dict__.items() if
                         k not in ['eval', 'exec', 'open', 'exit', 'quit']},
        "pd": pd,
        "np": np,
        "plt": plt,
        "FILE_IO_DIR": FILE_IO_DIR,  # Expose the safe directory path
    }

    output_buffer = io.StringIO()
    try:
        # Redirect stdout to capture print statements
        with redirect_stdout(output_buffer):
            exec(code, restricted_globals)

        # After execution, plt may have a figure ready to be saved.
        if plt.get_fignums():
            fig = plt.gcf()
            plot_filename = f"plot_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.png"
            plot_path = os.path.join(FILE_IO_DIR, plot_filename)
            fig.savefig(plot_path)
            plt.close(fig)  # Close the figure to free memory
            print(f"\n[Interpreter Note] Plot saved as '{plot_filename}'")

    except Exception:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        tb_string = ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        return f"Execution Error:\n{tb_string}"

    captured_output = output_buffer.getvalue()
    if not captured_output:
        return "Success: Code executed with no printed output."

    return f"Execution successful. Output:\n{captured_output}"


# --- Tool 1: Execute a raw string of Python code ---
def execute_python_code(code: str) -> str:
    """
    Executes a snippet of Python code in a sandboxed environment and returns its output.
    Ideal for quick calculations, data manipulation, and dynamic plotting.

    SECURITY WARNING: This tool executes arbitrary Python code. While it runs in a restricted
    environment, it should be used with caution. It has access to libraries like pandas,
    numpy, and matplotlib for data analysis and visualization. Any generated plots
    or files are saved to the secure workspace.

    Args:
        code: A string containing the Python code to execute.
    """
    print(f"--- [Alice/CodeInterpreter] --- Executing code snippet:\n{code}")
    return _execute_sandboxed_code(code)


# --- Tool 2: Run a Python file from the workspace ---
def run_python_file(file_path: str) -> str:
    """
    Executes a Python file from the workspace in a sandboxed environment.
    This is the primary tool for running scripts, applications, or tests that are
    saved in the workspace. The script runs with the same restrictions as
    `execute_python_code` (e.g., no 'os' or 'subprocess' access).

    Args:
        file_path: The path to the Python file within the workspace (e.g., 'my_script.py' or 'project/main_window.py').
    """
    print(f"--- [Alice/CodeInterpreter] --- Preparing to run file: {file_path}")

    # Security: Use the robust validation function
    full_path = _resolve_and_validate_path(file_path)
    if not full_path:
        return f"Security Error: Path '{file_path}' is invalid or outside the allowed workspace."

    if not os.path.exists(full_path):
        return f"File Error: The file '{file_path}' does not exist in the workspace."

    if not os.path.isfile(full_path):
        return f"File Error: The path '{file_path}' is a directory, not a file."

    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            code_to_run = f.read()
        print(f"--- [Alice/CodeInterpreter] --- Executing file contents:\n{code_to_run}")
        return _execute_sandboxed_code(code_to_run)
    except Exception as e:
        return f"File Read Error: Could not read the file '{file_path}'. Reason: {e}"


# --- Tool 3: Run a Python Application from a project directory ---
def run_python_application(project_directory: str, timeout: int = 120, is_test=True) -> str:
    """
    Runs a Python application from a specified project directory in the workspace.
    This tool automatically performs the following steps:
    1. Locates a standard entry point file (main_window.py, app.py, or application.py).
    2. Finds the Python virtual environment (.venv) inside the project directory.
    3. Executes the application using the virtual environment's Python interpreter.
    This is the primary tool for starting applications like web servers or complex scripts
    that have their own dependencies, as it runs them in an isolated process.

    Args:
        project_directory: The relative path to the project directory in the workspace.
        timeout: The maximum time in seconds to wait for the command to execute. Defaults to 120.
    """
    print(f"--- [Alice/CodeInterpreter] --- Preparing to run application in '{project_directory}'")

    # 1. Validate the project directory path and get its absolute path
    abs_project_path = _resolve_and_validate_path(project_directory)
    if not abs_project_path:
        return f"Security Error: The project path '{project_directory}' is invalid or outside the allowed workspace."
    if not os.path.isdir(abs_project_path):
        return f"Error: The specified project path '{project_directory}' does not exist or is not a directory."

    # 2. Find the entry point file
    entry_point_candidates = ['main_window.py', 'app.py', 'application.py']
    entry_point_filename = None
    for candidate in entry_point_candidates:
        if os.path.exists(os.path.join(abs_project_path, candidate)):
            entry_point_filename = candidate
            print(f"--- [Alice/CodeInterpreter] --- Found entry point: '{entry_point_filename}'")
            break

    if not entry_point_filename:
        return f"Error: Could not find a standard entry point ({', '.join(entry_point_candidates)}) in '{project_directory}'."

    # 3. Find the virtual environment's Python executable
    venv_python_path = os.path.join(abs_project_path, '.venv', 'bin', 'python')
    if not os.path.exists(venv_python_path):
        return f"Error: Python virtual environment not found at '{os.path.join(project_directory, '.venv/bin/python')}'. Please ensure the venv exists (e.g., with 'uv venv')."

    # 4. Construct and execute the command
    command_to_run = f"{venv_python_path} {entry_point_filename}"
    print(
        f"--- [Alice/CodeInterpreter] --- Executing command: '{command_to_run}' in working directory: '{abs_project_path}'")

    # Use the existing robust shell execution tool, passing the project path as the working directory
    result = execute_shell_command(
        command=command_to_run,
        timeout=timeout,
        working_dir=abs_project_path
    )

    return f"Application execution result for '{project_directory}':\n{result}"

def get_mapping():
    return {
        "python.execute": execute_python_code,
        "python.run_file": run_python_file,
        "python.run_application": run_python_application,
    }
