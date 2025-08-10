import json
import os
from typing import List

from ._base import FILE_IO_DIR,  TODO_FILE

def _load_todos() -> List[str]:
    """Loads the to-do list from the JSON file."""
    if not os.path.exists(TODO_FILE):
        return []
    try:
        with open(TODO_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get("tasks", [])
    except (json.JSONDecodeError, IOError):
        return []

def _save_todos(tasks: List[str]):
    """Saves the to-do list to the JSON file."""
    with open(TODO_FILE, 'w', encoding='utf-8') as f:
        json.dump({"tasks": tasks}, f, indent=2)

def add_todo_item(item: str) -> str:
    """Adds a new item to the to-do list."""
    if not FILE_IO_DIR: return "Error: To-do list is disabled due to a configuration issue."
    tasks = _load_todos()
    if item not in tasks:
        tasks.append(item)
        _save_todos(tasks)
        return f"Success: Added '{item}' to the to-do list."
    else:
        return f"Info: '{item}' is already on the to-do list."

def view_todo_list() -> str:
    """Displays all items currently on the to-do list."""
    if not FILE_IO_DIR: return "Error: To-do list is disabled due to a configuration issue."
    tasks = _load_todos()
    if not tasks:
        return "The to-do list is currently empty."

    report = "Current to-do list:\n"
    for i, task in enumerate(tasks):
        report += f"{i + 1}. {task}\n"
    return report.strip()

def complete_todo_item(item_number: int) -> str:
    """Removes an item from the to-do list by its number, marking it as complete."""
    if not FILE_IO_DIR: return "Error: To-do list is disabled due to a configuration issue."
    tasks = _load_todos()
    # Adjust for 1-based indexing from the user
    index = item_number - 1
    if 0 <= index < len(tasks):
        removed_item = tasks.pop(index)
        _save_todos(tasks)
        return f"Success: Completed and removed '{removed_item}' from the to-do list."
    else:
        return f"Error: Invalid item number. There are only {len(tasks)} items on the list. Use 'view_todo_list' to see them."


def get_mapping():
    return {
        "todo.add": add_todo_item,  # Adds a new task or item to the user's to-do list.
        "todo.complete": complete_todo_item,  # Marks an item as complete and removes it from the list.
        "todo.view": view_todo_list,  # Displays all items currently in the to-do list.
    }