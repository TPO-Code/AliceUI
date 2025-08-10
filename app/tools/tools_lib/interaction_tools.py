# backend/alice/tools_lib/interaction_tools.py
from typing import List, Optional

def ask_user(question: str, options: Optional[List[str]] = None) -> str:
    """
    Pauses execution and asks the user for input. This is NOT a tool for asking general questions.
    Use this ONLY when you are blocked and require a specific piece of information from the user
    to continue your current task, or when you need confirmation for a sensitive action.
    The main control loop will handle presenting the question to the user and returning their answer.

    Args:
        question: The question to ask the user.
        options: An optional list of choices for the user to select from.
    """
    print(f"--- [Alice/Human-Interaction] --- Posing question to user: {question}")

    # This tool doesn't *do* anything on the backend. It returns a specially formatted
    # string that the agent's main loop should be designed to catch.
    # The loop would then prompt the user, and re-inject the answer into the agent's context.
    options_str = ""
    if options:
        options_str = "\nOptions: " + ", ".join(options)

    # The special format 'USER_INPUT_REQUIRED::' is a signal to the calling code.
    return f"USER_INPUT_REQUIRED::{question}{options_str}"

def get_mapping():
    return {
        "human.ask": ask_user,
    }