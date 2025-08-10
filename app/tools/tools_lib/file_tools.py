# backend/alice/tools_lib/file_tools.py
import os
import re
import difflib
import fnmatch
import shutil
from typing import Optional

# Correctly import the robust validation function from _base
from ._base import FILE_IO_DIR, _resolve_and_validate_path


def save_file(path: str, content: str) -> str:
    """Saves content to a file within the allowed directory."""
    # This function already uses the correct validation method. No changes needed.
    safe_abs_path = _resolve_and_validate_path(path)

    if not safe_abs_path:
        return f"Error: The path '{path}' is invalid or outside the allowed directory."

    try:
        os.makedirs(os.path.dirname(safe_abs_path), exist_ok=True)
        with open(safe_abs_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"--- [Alice/Save-File] --- Successfully saved file to '{path}'")
        return f"Successfully saved content to the file '{path}'."
    except Exception as e:
        return f"Error: Failed to save file '{path}'. Reason: {e}"


def read_file(path: str) -> str:
    """Reads the content of a text file from the secure workspace."""
    print(f"--- [Alice/Read-File] --- Attempting to read '{path}'")

    # UPDATED: Use the new validation function
    safe_abs_path = _resolve_and_validate_path(path)
    if not safe_abs_path:
        return f"Error: The path '{path}' is invalid or outside the allowed directory."

    try:
        if not os.path.exists(safe_abs_path): return f"Error: File '{path}' not found."
        if not os.path.isfile(safe_abs_path): return f"Error: Path '{path}' is a directory, not a file."

        with open(safe_abs_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Error: Could not read file '{path}'. Reason: {e}"


def append_to_file(path: str, content: str) -> str:
    """Appends content to an existing file or creates the file if it doesn't exist."""
    print(f"--- [Alice/File-Append] --- Attempting to append to '{path}'")

    # UPDATED: Use the new validation function
    safe_abs_path = _resolve_and_validate_path(path)
    if not safe_abs_path:
        return f"Error: The path '{path}' is invalid or outside the allowed directory."

    try:
        # Ensure parent directory exists, similar to save_file
        os.makedirs(os.path.dirname(safe_abs_path), exist_ok=True)
        with open(safe_abs_path, 'a', encoding='utf-8') as f:
            f.write('\n' + content)
        return f"Success: Content appended to '{path}'."
    except Exception as e:
        return f"Error: Could not append to file '{path}'. Reason: {e}"


def delete_file(path: str) -> str:
    """Deletes a file from the secure workspace."""
    print(f"--- [Alice/File-Delete] --- Attempting to delete '{path}'")

    # UPDATED: Use the new validation function
    safe_abs_path = _resolve_and_validate_path(path)
    if not safe_abs_path:
        return f"Error: The path '{path}' is invalid or outside the allowed directory."

    try:
        if not os.path.exists(safe_abs_path): return f"Error: File '{path}' not found."
        if not os.path.isfile(safe_abs_path): return f"Error: Path '{path}' is a directory, not a file."

        os.remove(safe_abs_path)
        return f"Success: File '{path}' was deleted."
    except Exception as e:
        return f"Error: Could not delete file '{path}'. Reason: {e}"


def move_item(source: str, destination: str) -> str:
    """Moves or renames a file or directory within the secure workspace."""
    print(f"--- [Alice/FS-Move] --- Attempting to move '{source}' to '{destination}'")

    # UPDATED: Use the new validation function for both source and destination
    source_path = _resolve_and_validate_path(source)
    if not source_path:
        return f"Error: Invalid or unsafe source path '{source}'."

    dest_path = _resolve_and_validate_path(destination)
    if not dest_path:
        return f"Error: Invalid or unsafe destination path '{destination}'."

    if not os.path.exists(source_path):
        return f"Error: Source '{source}' not found."

    try:
        # The validation functions already ensure both paths are within the workspace.
        shutil.move(source_path, dest_path)
        return f"Success: Moved '{source}' to '{destination}'."
    except Exception as e:
        return f"Error: Could not move item. Reason: {e}"


def list_files(path: str = '.') -> str:
    """Lists files in a specific directory within the workspace."""
    print(f"--- [Alice/List-Files] --- Listing files in '{path}'.")

    # UPDATED: Validate the path before listing
    safe_abs_path = _resolve_and_validate_path(path)
    if not safe_abs_path:
        return f"Error: The path '{path}' is invalid or outside the allowed directory."
    if not os.path.isdir(safe_abs_path):
        return f"Error: The path '{path}' is not a directory."

    try:
        items = os.listdir(safe_abs_path)
        if not items: return f"No files or directories found in '{path}'."

        files = [f for f in items if os.path.isfile(os.path.join(safe_abs_path, f))]

        if not files: return f"No files found in '{path}' (only subdirectories)."
        return f"Files available in '{path}':\n- " + "\n- ".join(files)
    except Exception as e:
        return f"Error: Could not list files in '{path}'. Reason: {e}"


def find_files(name_pattern: Optional[str] = None, content_regex: Optional[str] = None) -> str:
    """Searches for files within the secure directory based on a name pattern and/or a text pattern inside the file."""
    # This function operates on the root FILE_IO_DIR and is inherently safe. No changes needed.
    print(f"--- [Alice/File-Finder] --- Searching with pattern: '{name_pattern}', content: '{content_regex}'")
    if not FILE_IO_DIR: return "Error: File I/O is disabled due to a configuration issue."
    if not name_pattern and not content_regex: return "Error: You must provide at least a name_pattern or a content_regex."
    found_files = []
    for root, _, files in os.walk(FILE_IO_DIR):
        matching_filenames = []
        if name_pattern:
            for filename in files:
                if fnmatch.fnmatch(filename, name_pattern): matching_filenames.append(os.path.join(root, filename))
        else:
            matching_filenames = [os.path.join(root, filename) for filename in files]
        if content_regex:
            try:
                prog = re.compile(content_regex)
                for filepath in matching_filenames:
                    try:
                        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                            if prog.search(f.read()):
                                found_files.append(os.path.relpath(filepath, FILE_IO_DIR))
                    except Exception:
                        continue
            except re.error as e:
                return f"Error: Invalid regular expression: {e}"
        else:
            found_files.extend([os.path.relpath(f, FILE_IO_DIR) for f in matching_filenames])
    if not found_files: return "No files found matching your criteria."
    return "Found the following files:\n- " + "\n- ".join(sorted(list(set(found_files))))


def compare_files(file1: str, file2: str) -> str:
    """Compares two text files and returns a summary of their differences (a 'diff')."""
    print(f"--- [Alice/File-Compare] --- Comparing '{file1}' and '{file2}'")

    # UPDATED: Use the new validation function for both files
    path1 = _resolve_and_validate_path(file1)
    if not path1: return f"Error: The path for file 1 '{file1}' is invalid or outside the allowed directory."
    path2 = _resolve_and_validate_path(file2)
    if not path2: return f"Error: The path for file 2 '{file2}' is invalid or outside the allowed directory."

    if not os.path.exists(path1): return f"Error: File '{file1}' not found."
    if not os.path.exists(path2): return f"Error: File '{file2}' not found."

    try:
        with open(path1, 'r', encoding='utf-8') as f1:
            lines1 = f1.readlines()
        with open(path2, 'r', encoding='utf-8') as f2:
            lines2 = f2.readlines()
        diff = '\n'.join(difflib.unified_diff(lines1, lines2, fromfile=file1, tofile=file2, lineterm=''))
        if not diff: return f"The files '{file1}' and '{file2}' are identical."
        return f"Differences between '{file1}' and '{file2}':\n\n{diff}"
    except Exception as e:
        return f"Error: Could not compare files. Reason: {e}"


# --- Mapping Function ---
def get_mapping():
    return {
        "file.save": save_file,
        "file.read": read_file,
        "file.list": list_files,
        "file.append": append_to_file,
        "file.delete": delete_file,
        "file.find": find_files,
        "file.compare": compare_files,
        "fs.move": move_item,
    }