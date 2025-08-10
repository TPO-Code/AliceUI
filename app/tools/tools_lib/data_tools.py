import io
import json
import os
import time

import jmespath
import pandas as pd
import pandas.api.types as ptypes

import matplotlib.pyplot as plt

from ._base import FILE_IO_DIR, _resolve_and_validate_path


def get_csv_info(filename: str) -> str:
    """Reads a CSV file and returns a summary of its structure, columns, and the first few rows."""
    print(f"--- [Alice/Data-Analyze] --- Getting info for CSV: '{filename}'")

    # Use the new function to get a safe, absolute path
    safe_abs_path = _resolve_and_validate_path(filename)

    if not safe_abs_path:
        return f"Error: The path '{filename}' is invalid or outside the allowed directory."

    if not os.path.exists(safe_abs_path):
        return f"Error: File '{filename}' not found."

    try:
        df = pd.read_csv(safe_abs_path)

        # Capture df.info() which prints to stdout
        info_buffer = io.StringIO()
        df.info(buf=info_buffer)
        info_str = info_buffer.getvalue()

        head_str = df.head().to_string()

        return f"File Information for '{filename}':\n\n--- Structure & Data Types ---\n{info_str}\n\n--- First 5 Rows ---\n{head_str}"
    except Exception as e:
        return f"Error: Failed to process CSV file '{filename}'. Reason: {e}"


def create_plot_from_csv(filename: str, plot_type: str = 'line', title: str = '') -> str:
    """
    Generates a plot from a CSV, automatically detecting if a header exists.
    - If no header: Plots values against their row index.
    - If header: Plots the second column against the first.
    """

    def _has_header(filepath):  # This helper is fine as it receives a validated path
        try:
            with open(filepath, 'r') as f:
                first_line = f.readline()
                if not first_line.strip(): return False
                for item in first_line.strip().split(','):
                    try:
                        float(item)
                    except ValueError:
                        return True
                return False
        except Exception:
            return True

    print(f"--- [Alice/Data-Analyze] --- Auto-plotting from '{filename}'")

    # Validate the INPUT file path
    safe_input_path = _resolve_and_validate_path(filename)
    if not safe_input_path:
        return f"Error: The input path '{filename}' is invalid or outside the allowed directory."
    if not os.path.exists(safe_input_path):
        return f"Error: Input file '{filename}' not found."

    try:
        has_header = _has_header(safe_input_path)
        header_param = 0 if has_header else None
        print(f"--- [Alice/Data-Analyze] --- Detected header: {has_header}")
        df = pd.read_csv(safe_input_path, header=header_param)

        # ... (plotting logic for x/y data is unchanged) ...
        num_columns = len(df.columns)
        if num_columns == 0:
            return "Error: The CSV file is empty and has no columns to plot."
        elif num_columns == 1:
            x_data, y_data = df.index, df.iloc[:, 0]
            x_label, y_label = 'Index', df.columns[0] if has_header else 'Value'
        else:
            x_data, y_data = df.iloc[:, 0], df.iloc[:, 1]
            x_label, y_label = df.columns[0], df.columns[1]

        if not ptypes.is_numeric_dtype(y_data):
            return f"Error: The chosen Y-axis column ('{y_label}') contains non-numeric data and cannot be plotted."

        plt.figure(figsize=(10, 6))
        if plot_type == 'bar':
            plt.bar(x_data, y_data)
        elif plot_type == 'scatter':
            plt.scatter(x_data, y_data)
        else:
            plt.plot(x_data, y_data)
        plt.xlabel(x_label);
        plt.ylabel(y_label)
        plt.title(title if title else f'{y_label} vs. {x_label}')
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()

        # Securely generate and validate the OUTPUT file path
        base_name = os.path.basename(filename)  # Prevents path traversal from input filename
        output_filename = f"plot_{os.path.splitext(base_name)[0]}_{int(time.time())}.png"

        safe_output_path = _resolve_and_validate_path(output_filename)
        if not safe_output_path:
            return f"Error: Could not create a safe path for the plot image. The generated name '{output_filename}' was invalid."

        plt.savefig(safe_output_path)
        plt.close()

        # Return the relative output filename for the user.
        return f"Success: Plot generated and saved to '{output_filename}'."

    except Exception as e:
        return f"Error: Failed to create plot from '{filename}'. Reason: {e}"


def query_json_file(filename: str, query: str) -> str:
    """
    Loads a JSON file and queries it using a JMESPath expression to extract specific data.
    """
    print(f"--- [Alice/JSON-Query] --- Querying '{filename}' with '{query}'")

    # Use the new function to get a safe, absolute path
    safe_abs_path = _resolve_and_validate_path(filename)

    if not safe_abs_path:
        return f"Error: The path '{filename}' is invalid or outside the allowed directory."

    if not os.path.exists(safe_abs_path):
        return f"Error: File '{filename}' not found."

    try:
        with open(safe_abs_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        result = jmespath.search(query, data)

        if result is None:
            return f"The query '{query}' returned no results or an invalid path."
        else:
            return f"Query result from '{filename}':\n{json.dumps(result, indent=2)}"

    except json.JSONDecodeError:
        return f"Error: Failed to parse '{filename}'. It is not a valid JSON file."
    except jmespath.exceptions.JMESPathError as e:
        return f"Error: Invalid JMESPath query: {e}"
    except Exception as e:
        return f"Error: An unexpected error occurred. Reason: {e}"


def get_mapping():
    return {
        "data.create_plot_from_csv": create_plot_from_csv,  # Generates a plot (line, bar, scatter) from a CSV file.
        "data.get_csv_info": get_csv_info,  # Reads a CSV and returns a summary of its structure and head.
        "data.query_json": query_json_file,  # Loads and queries a JSON file using a JMESPath expression.

    }