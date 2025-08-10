# tools_lib/_base.py
import json
import os
from pathlib import Path

from utils.config import config


# --- Shared Configuration Loader ---
def get_and_validate_path(config_obj, key: str, default: str) -> str:
    """
    Gets a path from the config, validates it, and logs a warning if not absolute.
    """
    path_str = config_obj.get(key, default)
    expanded_path = os.path.expanduser(path_str)
    if not os.path.isabs(expanded_path):
        print(
            f"Configuration key '{key}' has a relative path: '{path_str}'. "
            f"It's highly recommended to use an absolute path in your config file."
        )
    return expanded_path

def save_list_to_json(data_list, filename):
    """
    Saves a list of items to a JSON file, creating parent
    directories if they don't exist.

    Args:
        data_list (list): The list to be saved.
        filename (str or Path): The name of the file to save to.
    """
    try:
        # Convert the filename string to a Path object
        file_path = Path(filename)

        # Create the parent directory structure if it doesn't exist.
        # parents=True: creates all necessary parent directories (like mkdir -p)
        # exist_ok=True: doesn't raise an error if the directory already exists
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # We use 'w' (write) mode to overwrite the file if it exists.
        # 'x' (exclusive creation) would fail on subsequent runs.
        with open(file_path, 'w') as f:
            json.dump(data_list, f, indent=4)
        print(f"Successfully saved list to {filename}")
    except (IOError, TypeError) as e:
        print(f"Error saving to file: {e}")

def load_list_from_json(filename):
    """
    Loads a list of items from a JSON file.

    Args:
        filename (str): The name of the file to load from (e.g., 'data.json').

    Returns:
        list: The list loaded from the file, or an empty list if an error occurs.
    """
    try:
        with open(filename, 'r') as f:
            # json.load() reads from a file-like object and deserializes the JSON to a Python object.
            data_list = json.load(f)
        print(f"Successfully loaded list from {filename}")
        return data_list
    except FileNotFoundError:
        print(f"Error: The file {filename} was not found.")
        return []
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from the file {filename}.")
        return []
    except (IOError, TypeError) as e:
        print(f"Error loading from file: {e}")
        return []

# --- Shared Constants ---
# These are loaded here so other tool modules can import them directly.
FILE_IO_DIR = get_and_validate_path(
    config, "alice.tools.file_io_directory", "./data/io"
)
MEMORY_FILE = get_and_validate_path(
    config, "alice.tools.memory_file", "./data/memory.json"
)
TODO_FILE = get_and_validate_path(
    config, "alice.tools.todo_file", "./data/todo.json"
)
SUMMARIZATION_MODEL = config.get("alice.tools.summarization_model", "llama3.1:8b")
CALENDAR_BASE = config.get("calendar.host", "http://localhost:8000")
OLLAMA_URL = config.get('ollama.url')
GITHUB_USERNAME = config.get("alice.tools.github.username", "None")
GITHUB_API_KEY = config.get("alice.tools.github.api_key", "None")
# --- Directory Setup ---
if FILE_IO_DIR:
    os.makedirs(FILE_IO_DIR, exist_ok=True)
    print(f"--- [Alice/Tools/_base] File I/O enabled in directory: {FILE_IO_DIR}")
else:
    print(
        "--- [Alice/Tools/_base] [FATAL ERROR] 'alice.file_io_directory' is not set or is not an absolute path. File I/O tools will be disabled.")


# --- Shared Helper Functions ---
def _resolve_and_validate_path(relative_path: str) -> str | None:
    """
    Resolves a relative path against FILE_IO_DIR and validates it's safe.
    This is the primary security function for all file/directory operations.

    It prevents:
    - Absolute paths (e.g., /etc/passwd)
    - Path traversal attacks (e.g., ../../)
    - Access to any file or directory outside of FILE_IO_DIR.

    Args:
        relative_path: The path provided by the LLM, relative to FILE_IO_DIR.

    Returns:
        The absolute, validated path if it's safe.
        None if the path is unsafe or invalid.
    """
    if not FILE_IO_DIR:
        print("--- [Alice/File-IO] [ERROR] FILE_IO_DIR is not configured. Operation cancelled.")
        return None

    # Security Check 1: Disallow absolute paths.
    if os.path.isabs(relative_path):
        print(f"--- [Alice/File-IO] [SECURITY WARNING] Absolute paths are not allowed: '{relative_path}'.")
        return None

    # Security Check 2: Canonicalize the path to resolve '..' and symlinks.
    # This is the core of the security check.
    base_path = os.path.realpath(FILE_IO_DIR)
    intended_path = os.path.realpath(os.path.join(base_path, relative_path))

    # Security Check 3: Ensure the resolved path is within the base directory.
    if os.path.commonpath([base_path, intended_path]) != base_path:
        print(f"--- [Alice/File-IO] [SECURITY WARNING] Path traversal attempt blocked for: '{relative_path}'")
        return None

    return intended_path

def _format_timedelta(seconds):
    """Formats a given number of seconds into a human-readable string representation of days, hours, and minutes.

Args:
    seconds (int): The total number of seconds to format.

Returns:
    str: A string describing the time in terms of days, hours, and minutes. If the input is less than a minute, returns "less than a minute"."""
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    parts = []
    if days > 0: parts.append(f"{int(days)} day{'s' if days != 1 else ''}")
    if hours > 0: parts.append(f"{int(hours)} hour{'s' if hours != 1 else ''}")
    if minutes > 0: parts.append(f"{int(minutes)} minute{'s' if minutes != 1 else ''}")
    return ", ".join(parts) or "less than a minute"