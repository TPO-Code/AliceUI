# backend/alice/tools_lib/research_tools.py
import re
import json

from .web_tools import search_web, extract_text_from_url
from .github_tools import search_repositories
from .state_tools import set_state, append_to_list_state
from .content_tools import summarize_text


def research_github_repos(query: str, num_results: int = 3) -> str:
    """
    Finds GitHub repos, saves them to the blackboard, and returns a structured
    response containing a command for the system to execute the next step.
    """
    print(f"--- [Alice/Research] --- Starting GitHub repo research for query: '{query}'")
    search_result_str = search_repositories(query=query, limit=num_results)

    if search_result_str.startswith("Error:"):
        return search_result_str
    try:
        repos = json.loads(search_result_str)
        if not repos:
            return json.dumps({"status": "Success", "summary": "Search returned no repositories."})

        set_state('research_results', repos)
        repo_names = [repo['full_name'] for repo in repos]

        # --- THE FINAL PATTERN: A DIRECT COMMAND TO THE PYTHON LOOP ---
        structured_response = {
            "status": "CHAINED_ACTION_REQUIRED",
            "summary": f"Found {len(repo_names)} repositories and saved them to the blackboard.",
            # This key will be detected by the main loop.
            "force_next_tool_call": {
                "name": "state.get",
                "arguments": {"key": "research_results"}
            }
        }
        return json.dumps(structured_response, indent=2)

    except json.JSONDecodeError:
        return json.dumps({"status": "Error", "summary": "Failed to parse the GitHub search results."})


# The rest of the file (web_summarize, TOOLS, get_mapping) remains the same as your corrected version.
# ...
# --- Generic Web/Shopping Workflow Tool ---
def research_web_and_summarize(query: str, num_results: int = 3) -> str:
    """
    Performs a web search, reads the content of the top results, summarizes each one,
    and stores the summaries on the blackboard key 'research_summaries'.
    Ideal for comparing products, articles, or general topics from the web.
    """
    print(f"--- [Alice/Research] --- Starting web research and summarization for: '{query}'")

    # Step 1: Use the low-level web search tool
    search_results_str = search_web(query, num_results=num_results)
    if search_results_str.startswith("Error:") or "No results found" in search_results_str:
        return search_results_str

    urls = re.findall(r'https?://[^\s]+', search_results_str)
    if not urls:
        return "The web search returned results, but I couldn't extract any valid URLs to read."

    set_state('research_urls', urls)

    next_tool_call = {
        "role": "assistant",
        "content": f"Found {len(urls)} relevant web pages. Now processing the first one.",
        "tool_calls": [
            {
                "id": "tool-call-internal-web-step",
                "type": "function",
                "function": {
                    "name": "web.read",
                    "arguments": json.dumps({"url": urls[0]})
                }
            }
        ]
    }
    return json.dumps(next_tool_call)





def get_mapping():
    return {
        "research.github_repos": research_github_repos,
        "research.web_summarize": research_web_and_summarize,
    }