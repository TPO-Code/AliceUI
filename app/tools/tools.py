# tools/tools.py
import hashlib
import json
import time
from pathlib import Path

# --- Local Imports ---
from utils.embedding_service import embedding_model, EmbedServError
from tools.tools_lib import (
    calendar_tools, code_interpreter_tools, content_tools, data_tools,
    directory_tools, file_tools, github_tools, math_tools,
    interaction_tools, meetings_tools, project_tools,
    research_tools, state_tools, system_tools, time_tools,
    todo_tools, weather_tools, web_tools
)

# --- Configuration ---
TOP_K = 7
EMBEDDING_MODEL_NAME = embedding_model.model_name if embedding_model.client else "N/A"
TOOLS_COLLECTION_NAME = "llm_lora_tool_rag_db"
TOOLS_DIR = Path(__file__).resolve().parent
HASH_FILE_PATH = TOOLS_DIR / "rag_collection.hash"
CORE_TOOLS_TO_ALWAYS_INCLUDE = [
    "time.current_datetime",
    "state.set",
    "state.get",
    "state.list_keys",
    "interaction.human_ask"
]

# --- Global Tool Variables ---
ALL_TOOL_DEFINITIONS = []
TOOL_MAPPING = {}
TOOL_NAME_TO_DESCRIPTION = {}


def _load_all_tools_from_modules():
    """
    Loads all tool definitions and functions from the library modules.
    - Calls get_mapping() on each module for the functions.
    - Loads definitions from a corresponding .json file for each module.
    """
    global ALL_TOOL_DEFINITIONS, TOOL_MAPPING, TOOL_NAME_TO_DESCRIPTION

    tool_modules = [
        calendar_tools, code_interpreter_tools, content_tools, data_tools,
        directory_tools, file_tools, github_tools, math_tools,
        interaction_tools, meetings_tools, project_tools,
        research_tools, state_tools, system_tools, time_tools,
        todo_tools, weather_tools, web_tools
    ]

    for module in tool_modules:
        # 1. Get the callable functions from the module
        if not hasattr(module, 'get_mapping'):
            print(
                f"--- [Tools-Init] [WARNING] Module {module.__name__} is missing the 'get_mapping()' function. Skipping.")
            continue

        # Add the functions to our master mapping
        module_functions = module.get_mapping()
        TOOL_MAPPING.update(module_functions)

        # 2. Find and load the corresponding JSON definitions file
        try:
            # Get the path of the Python module file (e.g., /path/to/tools_lib/web_tools.py)
            module_path = Path(module.__file__)
            # Construct the path to the JSON file (e.g., /path/to/tools_lib/web_tools.json)
            json_path = module_path.with_suffix('.json')

            if not json_path.exists():
                print(
                    f"--- [Tools-Init] [WARNING] JSON file not found for module {module.__name__} at {json_path}. Skipping definitions.")
                continue

            # Load the tool definitions from the JSON file
            with open(json_path, 'r', encoding='utf-8') as f:
                module_definitions = json.load(f)

                # The JSON file might contain a single tool dict or a list of them
                if isinstance(module_definitions, list):
                    ALL_TOOL_DEFINITIONS.extend(module_definitions)
                elif isinstance(module_definitions, dict):
                    ALL_TOOL_DEFINITIONS.append(module_definitions)
                else:
                    print(f"--- [Tools-Init] [WARNING] Invalid format in {json_path}. Expected a JSON object or list.")

        except Exception as e:
            print(f"--- [Tools-Init] [ERROR] Failed to load or parse tools for {module.__name__}: {e}")

    # After loading everything, create the descriptions needed for RAG
    TOOL_NAME_TO_DESCRIPTION = {
        tool['function'][
            'name']: f"Tool name: {tool['function']['name']}. Description: {tool['function']['description']}"
        for tool in ALL_TOOL_DEFINITIONS
    }

    print(
        f"--- [Tools-Init] Successfully loaded {len(ALL_TOOL_DEFINITIONS)} tool definitions and {len(TOOL_MAPPING)} functions.")


# --- The rest of the file is UNCHANGED as it correctly uses the global variables ---
# (get_tools, _create_descriptions_hash, _synchronize_rag_collection, etc. are correct)

def get_tools(conversation: list[dict], turns: int = 2) -> (list[dict], dict[str, callable]):
    """
    Selects the most relevant tools by querying the EmbedServ RAG collection.
    """
    if not embedding_model.client:
        print("--- [Tools-RAG] [WARNING] Embedding service not available. Returning core tools.")
        core_tools_defs = [t for t in ALL_TOOL_DEFINITIONS if t['function']['name'] in CORE_TOOLS_TO_ALWAYS_INCLUDE]
        core_tools_map = {name: TOOL_MAPPING[name] for name in CORE_TOOLS_TO_ALWAYS_INCLUDE if name in TOOL_MAPPING}
        return core_tools_defs, core_tools_map

    goal_message = next((m for m in reversed(conversation) if m.get('role') == 'user'), None)
    if not goal_message: return [], {}
    goal_text = goal_message.get('content', '')

    recent_events = conversation[-turns:]
    tactical_parts = []
    for msg in recent_events:
        if msg.get('role') == 'user': continue
        role, content = msg.get('role'), msg.get('content')
        if content:
            tactical_parts.append(f"Role: {role}\nContent: {content}")
        elif msg.get('tool_calls'):
            tool_names = [tc['function']['name'] for tc in msg['tool_calls']]
            tactical_parts.append(f"Role: {role}\nAction: Called tools {', '.join(tool_names)}")

    query_text = (
        f"**User's Current Goal:**\n{goal_text}\n\n"
        f"**Immediate Situation (Last Agent/Tool Actions):**\n"
        f"{'---'.join(tactical_parts) if tactical_parts else 'No recent actions have been taken.'}"
    )

    print("--- [Tools-RAG] Querying EmbedServ for relevant tools...")
    try:
        results = embedding_model.client.query(
            collection_name=TOOLS_COLLECTION_NAME,
            query_texts=[query_text],
            n_results=TOP_K,
            model_name=EMBEDDING_MODEL_NAME
        )
        rag_results = results.get('metadatas', [[]])[0]
        rag_tool_names = [meta['tool_name'] for meta in rag_results]

        print(f"--- [Tools-RAG] RAG search selected Top-{len(rag_tool_names)} tools: {rag_tool_names}")
        selected_tools = [t for t in ALL_TOOL_DEFINITIONS if t['function']['name'] in rag_tool_names]
        selected_mapping = {name: TOOL_MAPPING[name] for name in rag_tool_names}

    except EmbedServError as e:
        print(f"--- [Tools-RAG] [ERROR] Failed to query EmbedServ collection: {e}")
        print("--- [Tools-RAG] [INFO] Returning core tools as a fallback.")
        rag_tool_names = []
        selected_tools = []
        selected_mapping = {}

    added_core_tools = []
    for tool_name in CORE_TOOLS_TO_ALWAYS_INCLUDE:
        if tool_name not in rag_tool_names:
            tool_def = next((t for t in ALL_TOOL_DEFINITIONS if t['function']['name'] == tool_name), None)
            if tool_def:
                selected_tools.append(tool_def)
                selected_mapping[tool_name] = TOOL_MAPPING[tool_name]
                added_core_tools.append(tool_name)

    if added_core_tools:
        print(f"--- [Tools-RAG] Added {len(added_core_tools)} core tools to context: {added_core_tools}")

    return selected_tools, selected_mapping


def _create_descriptions_hash(descriptions: list[str]) -> str:
    combined_descriptions = "\n".join(sorted(descriptions))
    sha256_hash = hashlib.sha256()
    sha256_hash.update(combined_descriptions.encode('utf-8'))
    return sha256_hash.hexdigest()

def _read_hash_from_file(file_path: Path) -> str | None:
    """Reads a hash string from a local file."""
    if not file_path.exists():
        return None
    try:
        return file_path.read_text().strip()
    except IOError as e:
        print(f"Error reading hash from file: {e}")
        return None

def _save_hash_to_file(hash_string: str, file_path: Path):
    """Saves a hash string to a local text file."""
    try:
        file_path.write_text(hash_string)
        print(f"Hash successfully saved to {file_path}")
    except IOError as e:
        print(f"Error saving hash to file: {e}")
def _synchronize_rag_collection():
    """
    Checks if the tool definitions have changed using a LOCAL HASH FILE
    and rebuilds the server-side RAG collection if necessary.
    """
    if not embedding_model.client:
        print("--- [Tools-RAG] [ERROR] Cannot synchronize RAG collection: Embedding service is not available.")
        return

    client = embedding_model.client

    # 1. Get the hash of the current local tool definitions
    all_descriptions = list(TOOL_NAME_TO_DESCRIPTION.values())
    current_hash = _create_descriptions_hash(all_descriptions)
    print(f"--- [Tools-RAG] Local tools hash: {current_hash}")

    # 2. Read the old hash from the LOCAL file.
    previous_hash = _read_hash_from_file(HASH_FILE_PATH)
    print(f"--- [Tools-RAG] Previous hash from file: {previous_hash}")

    # 3. If hashes match, we're done.
    if current_hash == previous_hash:
        print("--- [Tools-RAG] Hashes match. Assuming server RAG collection is up to date.")
        return

    # 4. If hashes DON'T match, rebuild the collection on the server.
    print("--- [Tools-RAG] Hashes differ. Rebuilding RAG collection on the server...")
    try:
        # Check if the collection exists on the server so we can delete it
        existing_collections = client.list_collections()
        if TOOLS_COLLECTION_NAME in existing_collections:
            print(f"--- [Tools-RAG] Deleting old collection '{TOOLS_COLLECTION_NAME}'...")
            client.delete_collection(TOOLS_COLLECTION_NAME)

        print(
            f"--- [Tools-RAG] Creating new collection '{TOOLS_COLLECTION_NAME}' with model '{EMBEDDING_MODEL_NAME}'...")
        client.create_collection(collection_name=TOOLS_COLLECTION_NAME, model_name=EMBEDDING_MODEL_NAME)

        # Add all the tools to the collection
        tool_names = list(TOOL_NAME_TO_DESCRIPTION.keys())
        descriptions_to_add = [TOOL_NAME_TO_DESCRIPTION[name] for name in tool_names]
        metadatas_to_add = [{'tool_name': name} for name in tool_names]

        print(f"--- [Tools-RAG] Adding {len(tool_names)} tools to the collection...")
        client.add_to_collection(
            collection_name=TOOLS_COLLECTION_NAME,
            items=descriptions_to_add,
            metadatas=metadatas_to_add,
            ids=tool_names,
            model_name=EMBEDDING_MODEL_NAME
        )

        # 5. After a successful rebuild, save the new hash to the LOCAL file.
        print(f"--- [Tools-RAG] Server collection successfully rebuilt. Saving new hash to local file...")
        _save_hash_to_file(current_hash, HASH_FILE_PATH)

    except EmbedServError as e:
        print(f"--- [Tools-RAG] [FATAL ERROR] An API error occurred while rebuilding the RAG collection: {e}")
        print(
            f"--- [Tools-RAG] [INFO] Please ensure EmbedServ is running and the model '{EMBEDDING_MODEL_NAME}' is available.")
    except Exception as e:
        print(f"--- [Tools-RAG] [FATAL ERROR] An unexpected error occurred: {e}")
        import traceback
        traceback.print_exc()


def initialize_tools():
    print("--- [Tools] Initializing Tool System ---")
    _load_all_tools_from_modules()
    _synchronize_rag_collection()
    print("--- [Tools] Initialization Complete ---")


initialize_tools()