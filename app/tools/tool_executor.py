# tools/tool_executor.py
import json


def execute_tool(tool_name: str, arguments: dict, tool_mapping: dict[str, callable]):
    """
    Finds and executes the appropriate tool function from a provided mapping.

    Args:
        tool_name: The name of the tool to execute.
        arguments: A dictionary of arguments for the tool.
        tool_mapping: A dictionary mapping tool names to their callable functions.
    """
    if tool_name not in tool_mapping:
        return json.dumps({"error": f"Tool '{tool_name}' not found in the current context."})

    tool_function = tool_mapping[tool_name]

    try:
        # Pass the arguments dictionary to the function using **
        result = tool_function(**arguments)

        # Ensure the result is a JSON string for consistency with the API
        if not isinstance(result, str):
            result = json.dumps(result)

        return result
    except TypeError as e:
        # This will catch mismatches in argument names
        return json.dumps({"error": f"Invalid arguments for tool '{tool_name}': {e}"})
    except Exception as e:
        # Catch any other unexpected errors during tool execution
        return json.dumps({"error": f"An unexpected error occurred in '{tool_name}': {e}"})