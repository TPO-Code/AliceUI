# tools_lib/directory_tools.py
import os
import shutil

from ._base import FILE_IO_DIR, _resolve_and_validate_path


# A more robust safety check for directory operations

import os
import shutil
# Assumes this import exists at the top of your directory_tools.py file
from ._base import FILE_IO_DIR, _resolve_and_validate_path


def create_directory(directory_name: str) -> str:
    """
    Creates a new directory (and any parent directories needed) within the secure workspace.
    """
    print(f"--- [Alice/Dir-Create] --- Attempting to create directory '{directory_name}'")

    # Use the new function to get a safe, absolute path
    safe_abs_path = _resolve_and_validate_path(directory_name)

    if not safe_abs_path:
        return f"Error: The path '{directory_name}' is invalid or outside the allowed directory."

    try:
        # The path is already validated, so we can use it directly.
        os.makedirs(safe_abs_path, exist_ok=True)
        return f"Success: Directory '{directory_name}' created or already exists."
    except Exception as e:
        return f"Error: Could not create directory '{directory_name}'. Reason: {e}"


def delete_directory(directory_name: str) -> str:
    """
    Recursively deletes a directory and all of its contents. Use with caution.
    """
    print(f"--- [Alice/Dir-Delete] --- Attempting to delete directory '{directory_name}'")

    # Use the new function to get a safe, absolute path
    safe_abs_path = _resolve_and_validate_path(directory_name)

    if not safe_abs_path:
        return f"Error: The path '{directory_name}' is invalid or outside the allowed directory."

    # Additional safety checks before deleting
    if not os.path.isdir(safe_abs_path):
        return f"Error: '{directory_name}' is not a valid directory or does not exist."

    if safe_abs_path == os.path.realpath(FILE_IO_DIR):
        return "Error: Deleting the root workspace directory is not allowed."

    try:
        shutil.rmtree(safe_abs_path)
        return f"Success: Directory '{directory_name}' and all its contents have been deleted."
    except Exception as e:
        return f"Error: Could not delete directory '{directory_name}'. Reason: {e}"


def list_directory_tree(path: str = '.', max_depth: int = 3) -> str:
    """
    Lists files and directories in a tree structure starting from a given path within the workspace.
    - 'path' is relative to the workspace root. Use '.' for the root.
    - 'max_depth' limits how deep the tree goes to prevent excessive output.
    """
    print(f"--- [Alice/Dir-Tree] --- Listing tree for '{path}' with max_depth {max_depth}")

    # Use the new function to get a safe, absolute starting path
    safe_start_path = _resolve_and_validate_path(path)

    if not safe_start_path:
        return f"Error: The path '{path}' is invalid or outside the allowed directory."

    if not os.path.isdir(safe_start_path):
        return f"Error: Start path '{path}' is not a directory."

    # Clean up the display path for the header
    display_path = path.strip('./') or '.'
    tree_lines = [f"Listing for: /{display_path}"]

    for root, dirs, files in os.walk(safe_start_path, topdown=True):
        # Calculate depth relative to the starting path for correct indentation and pruning
        relative_path = os.path.relpath(root, safe_start_path)
        level = 0 if relative_path == '.' else len(relative_path.split(os.sep))

        # Pruning logic: If we are at max_depth, don't descend further
        if max_depth != -1 and level >= max_depth:
            dirs[:] = []  # This modifies dirs in-place to stop os.walk from descending

        indent = "    " * level
        # Don't re-print the root of the listing, it's in the header
        if relative_path != '.':
            tree_lines.append(f"{indent}└── {os.path.basename(root)}/")

        sub_indent = "    " * (level + 1)
        for f in sorted(files):
            tree_lines.append(f"{sub_indent}├── {f}")

        # If at max depth and there are dirs, show they exist but are truncated
        if max_depth != -1 and level >= max_depth and dirs:
            tree_lines.append(f"{sub_indent}└── [...]")

    return "\n".join(tree_lines)


def get_mapping():
    return {
        "directory.create": create_directory,
        "directory.delete": delete_directory,
        "directory.tree": list_directory_tree,
    }