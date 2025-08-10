# backend/alice/tools_lib/state_tools.py
import json
from typing import Any, List

# This dictionary will act as our in-memory blackboard.
# It will be managed (cleared) by the main Alice class.
_task_state = {}


def set_state(key: str, value: Any) -> str:
    """
    Saves a piece of information to the task's blackboard (working memory).
    This is for temporary data related to the CURRENT task only.
    It will be wiped clean on the next user request. Use this to store intermediate
    results like URLs, filenames, or calculated values needed for subsequent steps.

    Args:
        key: The unique name for the piece of information (e.g., 'discovered_url').
        value: The data to store. Can be a string, number, list, or dict.
    """
    global _task_state
    if not isinstance(key, str) or not key.strip():
        return "Error: Key must be a non-empty string."

    _task_state[key] = value
    # Use json.dumps to handle complex types in the confirmation message
    return f"Success: Set blackboard key '{key}' to '{json.dumps(value)}'."


def get_state(key: str) -> str:
    """
    Retrieves a piece of information from the task's blackboard using its key.

    Args:
        key: The key of the information to retrieve.
    """
    global _task_state
    value = _task_state.get(key)
    if value is not None:
        return f"Value for key '{key}': {json.dumps(value)}"
    else:
        return f"Error: No information found on the blackboard for key '{key}'."


def append_to_list_state(key: str, item: Any) -> str:
    """
    Finds a list in the blackboard and appends a new item to it.
    If the key doesn't exist or is not a list, it creates a new list.

    Args:
        key: The key for the list on the blackboard.
        item: The item to add to the list.
    """
    global _task_state
    current_value = _task_state.get(key)

    if current_value is None:
        _task_state[key] = [item]
    elif isinstance(current_value, list):
        current_value.append(item)
    else:
        return f"Error: The value at key '{key}' is not a list. Cannot append."

    return f"Success: Appended item to list at key '{key}'."


def list_all_state_keys() -> str:
    """
    Lists all keys currently stored on the task's blackboard.
    Useful for getting an overview of what has been learned in the current task.
    """
    global _task_state
    if not _task_state:
        return "The blackboard is currently empty."

    keys = list(_task_state.keys())
    return f"Keys currently on the blackboard: {', '.join(keys)}"


def clear_blackboard():
    """A helper function to be called by the main system, not as a tool for the LLM."""
    global _task_state
    _task_state.clear()
    print("--- [StateTools] Blackboard cleared for new request.")




def get_mapping():
    return {
        "state.set": set_state,
        "state.get": get_state,
        "state.append_to_list": append_to_list_state,
        "state.list_keys": list_all_state_keys,
    }