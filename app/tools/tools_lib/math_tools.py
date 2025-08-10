import math

def calculate(expression: str) -> str:
    """Calculates the result of a Python-style mathematical expression."""
    # ... (implementation is unchanged)
    print(f"--- [Alice/Calculate] --- : {expression}")
    try:
        allowed_globals = {"__builtins__": None, "math": math}
        result = eval(expression, allowed_globals)
        print(f"--- [Alice/Calculate] --- Result: {result}")
        return f"Result: {result}"
    except Exception as e:
        print(f"--- [Alice/Calculate] --- Error calculating expression: {e}")
        return f"Error calculating expression: {e}"


def get_mapping():
    return {
        "math.calculate": calculate,  # Evaluates a Python-style mathematical expression.
    }