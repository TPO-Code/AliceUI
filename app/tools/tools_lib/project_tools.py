# backend/alice/tools_lib/project_tools.py
import os

from ._base import FILE_IO_DIR
# This composite tool uses functions from other tool modules.
from .directory_tools import create_directory
from .file_tools import save_file
from .system_tools import execute_shell_command


def create_python_project(project_name: str, python_version: str = "3.11", create_venv: bool = True) -> str:
    """
    A composite tool that scaffolds a basic Python project structure using the `uv` toolchain.
    It creates a main directory, a 'main_window.py' file, a '.gitignore' file,
    a 'requirements.txt', and can optionally create a Python virtual environment.
    """

    def _log(message: str, indent: int = 0, status: str = ""):
        indent_str = "  " * indent
        status_str = f" [{status}]" if status else ""
        print(f"--- [Alice/Composite-Project] --- {indent_str}{message}{status_str}")

    def _scaffold_file(path: str, content: str, file_desc: str) -> str | None:
        _log(f"Creating {file_desc}...", indent=2)
        result = save_file(path, content)
        if "Error:" in result:
            _log(f"FAILED: Could not save {path}.", indent=3)
            _log(f"Details: {result}", indent=4)
            return f"Failed at Step 2 ({file_desc}): {result}"
        return None

    _log(f"Scaffolding Python project '{project_name}'")
    _log(f"Parameters: python_version='{python_version}', create_venv={create_venv}", indent=1)

    # Step 1: Create the root project directory
    _log("Step 1: Create project directory", indent=1)
    create_dir_result = create_directory(project_name)
    if "Error:" in create_dir_result:
        _log(f"FAILED: Could not create directory '{project_name}'.", indent=2, status="ERROR")
        return f"Failed at Step 1 (Create Directory): {create_dir_result}"
    _log("Directory created successfully.", indent=2, status="SUCCESS")

    # Step 2: Create standard project files
    _log("Step 2: Create standard project files", indent=1)
    files_to_create = {
        f"{project_name}/main_window.py": (
            f"# {project_name}/main_window.py\n\ndef main():\n    print(\"Hello from {project_name}!\")\n\nif __name__ == \"__main__\":\n    main()\n",
            "main_window.py"),
        f"{project_name}/.gitignore": (
            "# Python\n__pycache__/\n*.py[cod]\n*$py.class\n\n# Env / Tooling\n.env\n.venv\n.uv_cache/\n",
            ".gitignore"),
        f"{project_name}/requirements.txt": ("# Add your uv dependencies here\n", "requirements.txt"),
    }
    for path, (content, desc) in files_to_create.items():
        error = _scaffold_file(path, content, desc)
        if error:
            _log("Project creation FAILED", status="ERROR")
            return error
    _log("All files created successfully.", indent=2, status="SUCCESS")

    # Step 3: Optionally create a virtual environment using uv
    _log("Step 3: Handle virtual environment", indent=1)
    venv_result_str = "Skipped: Virtual environment creation was not requested."
    if create_venv:
        _log(f"Validating Python version '{python_version}'...", indent=2)
        allowed_versions = ['3.10', '3.11', '3.12', '3.13', '3.14']
        if python_version not in allowed_versions:
            error_msg = f"Invalid Python version '{python_version}'. Allowed versions are: {', '.join(allowed_versions)}."
            _log(error_msg, indent=3, status="ERROR")
            return f"Error: {error_msg}"
        _log("Validation successful.", indent=2, status="SUCCESS")

        # === THE FIX IS HERE ===
        # 1. The command is now *only* the program and its arguments. NO 'cd'.
        command = f"uv venv -p {python_version}"

        # 2. Define the full path to the directory where the command should run.
        project_dir_path = os.path.join(FILE_IO_DIR, project_name)

        # 3. Update the log to be more precise.
        _log(f"Running command: '{command}' in directory '{project_dir_path}'", indent=2)

        # 4. Pass the clean command and the working directory separately.
        venv_result = execute_shell_command(command, working_dir=project_dir_path)
        # =======================

        if "Error:" in venv_result or "Failed to find python" in venv_result:
            venv_result_str = f"Failed: UV could not create the virtual environment."
            _log(venv_result_str, indent=3, status="ERROR")
            _log(f"Tool Output: {venv_result}", indent=4)
        else:
            venv_result_str = f"Success: Created UV virtual environment with Python {python_version}."
            _log(venv_result_str, indent=3, status="SUCCESS")
    else:
        _log(venv_result_str, indent=2)

    # Final Report
    _log("Project scaffolding complete.", status="SUCCESS")
    report = (
        f"Project '{project_name}' created successfully.\n"
        f"- Directory: '{project_name}' created.\n"
        f"- Core files: `main_window.py`, `.gitignore`, `requirements.txt` created.\n"
        f"- Virtual Env: {venv_result_str}"
    )
    print("\n" + report)
    return report


def get_mapping():
    return {
        "project.create_python": create_python_project,
    }