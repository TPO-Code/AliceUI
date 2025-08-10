# backend/alice/tools_lib/github_tools.py
import os
import json
import requests

# --- Local Imports ---
from ._base import _resolve_and_validate_path, GITHUB_USERNAME, GITHUB_API_KEY
# We reuse the system's command execution tool for local git operations
from .system_tools import execute_shell_command
from .content_tools import summarize_text

# --- Helper Functions ---

def _get_auth_headers() -> dict:
    """Returns the authorization headers for GitHub API requests."""
    if not GITHUB_API_KEY:
        # No token, so no auth header. API will be rate-limited and can't access private repos.
        print("--- [Alice/GitHub] [WARNING] No GITHUB_API_KEY found. Proceeding with unauthenticated requests.")
        return {}
    return {
        "Authorization": f"token {GITHUB_API_KEY}",
        "Accept": "application/vnd.github.v3+json"
    }

def _get_api_url(endpoint: str) -> str:
    """Constructs a full GitHub API URL from an endpoint."""
    return f"https://api.github.com{endpoint}"

def _fetch_all_repos_data() -> list:
    print("[Alice/GitHub] attempting to get user repository data")
    """Internal helper to fetch raw repository data from the GitHub API."""
    if not GITHUB_API_KEY:
        # We raise an exception here that the main tool will catch
        raise ValueError("Error: Your GitHub API key (GITHUB_API_KEY) is not configured.")

    url = _get_api_url("/user/repos?sort=pushed&type=all&per_page=30")
    response = requests.get(url, headers=_get_auth_headers())

    if response.status_code == 401:
        raise PermissionError("Error: Authentication failed. Check your GitHub API key.")

    response.raise_for_status() # Raise an exception for other bad statuses (404, 500, etc.)
    print("[Alice/GitHub] successfully fetched user repository data")
    return response.json()

# Replace the old function with this corrected version

def list_my_repositories(view: str = 'simple') -> str:
    """
    Fetches and displays the user's repositories in different formats.
    - 'full': A detailed list with descriptions and dates.
    - 'simple': A numbered list of repository names only.
    - 'summary': A high-level AI-generated overview.
    """
    print(f"--- [Alice/GitHub] --- Fetching repositories with view: '{view}'")

    try:
        repos_data = _fetch_all_repos_data()
        if not repos_data:
            return "No repositories found for the authenticated user."

        # --- VIEW-BASED FORMATTING LOGIC ---

        if view == 'simple':
            # A clean, numbered list. Less likely to be summarized by the LLM.
            report_lines = [f"{i+1}. {repo['full_name']}" for i, repo in enumerate(repos_data)]
            return "\n".join(report_lines)

        elif view == 'summary':
            # The logic from our old summarize tool.
            full_list_for_context = []
            for repo in repos_data:
                visibility = "Private" if repo['private'] else "Public"
                line = (
                    f"- {repo['full_name']} [{visibility}]\n"
                    f"  Description: {repo.get('description', 'N/A')}\n"
                )
                full_list_for_context.append(line)

            prompt_for_summary = (
                "Based on the following list of GitHub repositories, please provide a brief, "
                "high-level summary of the user's main projects and technical interests.\n\n"
                f"Repository List:\n{''.join(full_list_for_context)}"
            )
            result=summarize_text(prompt_for_summary, length="paragraph")
            print(f"--- [Alice/GitHub] --- result:\n{result}\n")
            return result

        else: # Default to 'full' view
            report_lines = []
            for repo in repos_data:
                visibility = "Private" if repo['private'] else "Public"
                line = (
                    f"- {repo['full_name']} [{visibility}]\n"
                    f"  Description: {repo.get('description', 'N/A')}\n"
                    f"  Last Push: {repo['pushed_at']}"
                )
                report_lines.append(line)
            return "\n\n".join(report_lines)

    except (ValueError, PermissionError, requests.exceptions.RequestException) as e:
        # Catch errors from the helper function or the request itself
        return str(e)


def summarize_my_repositories() -> str:
    """
    A composite tool that fetches the user's repository list and then uses
    another AI model to generate a high-level summary of their projects.
    """
    print(f"--- [Alice/GitHub-Composite] --- Summarizing user's repositories.")

    # Step 1: Get the raw data using the other tool
    repo_list_str = list_my_repositories()

    if repo_list_str.startswith("Error:") or repo_list_str.startswith("No repositories"):
        return repo_list_str

    # Step 2: Pass the raw data to the summarization tool
    prompt_for_summary = (
        "Based on the following list of GitHub repositories, please provide a brief, "
        "high-level summary of the user's main projects and technical interests. "
        "Focus on themes like 'LLM tools', 'system optimization', or 'creative interfaces'. "
        "Do not just repeat the list.\n\n"
        f"Repository List:\n{repo_list_str}"
    )

    summary = summarize_text(prompt_for_summary, length="paragraph")

    return summary
# --- Low-Level Tools (Can be used by composite tools or directly) ---

def search_repositories(query: str, limit: int = 5) -> str:
    """Searches for public repositories on GitHub using the API."""
    print(f"--- [Alice/GitHub] --- Searching for repositories with query: '{query}'")
    if not query:
        return "Error: Search query cannot be empty."

    url = _get_api_url(f"/search/repositories?q={query}&per_page={limit}")
    try:
        response = requests.get(url, headers=_get_auth_headers())
        response.raise_for_status()
        data = response.json()

        if not data.get("items"):
            return f"No repositories found for '{query}'."

        results = [{
            "full_name": item["full_name"],
            "url": item["html_url"],
            "description": item["description"],
            "stars": item["stargazers_count"]
        } for item in data["items"]]

        return json.dumps(results, indent=2)
    except requests.exceptions.RequestException as e:
        return f"Error: Failed to search GitHub. Reason: {e}"

def clone_repository(repo_url: str, depth: int = 0, timeout: int = 300) -> str:
    """
    Clones a Git repository into a subdirectory of the secure file I/O directory.
    Handles existing directories by creating a uniquely named folder.
    """
    try:
        # Extract a clean, simple name for the directory.
        base_repo_name = repo_url.split('/')[-1].replace('.git', '')
        # Sanitize to prevent characters that are invalid in directory names.
        base_repo_name = "".join(c for c in base_repo_name if c.isalnum() or c in ('_', '-')).strip()

        if not base_repo_name:
            return f"Error: Could not extract a valid directory name from the repo URL '{repo_url}'."

        # Find a unique directory name to clone into, preventing overwrites.
        repo_name = base_repo_name
        counter = 1
        # Use the secure validation function to get the absolute path for checking existence.
        while _resolve_and_validate_path(repo_name) and os.path.exists(_resolve_and_validate_path(repo_name)):
            repo_name = f"{base_repo_name}_{counter}"
            counter += 1

        # Final security check on the chosen name before executing the command.
        safe_clone_path = _resolve_and_validate_path(repo_name)
        if not safe_clone_path:
             # This is a fail-safe, should rarely be hit if sanitization is correct.
             return f"Error: The derived directory name '{repo_name}' is invalid or unsafe."

        if repo_name != base_repo_name:
            print(f"--- [Alice/GitHub] --- Directory '{base_repo_name}' exists. Cloning into '{repo_name}' instead.")

        depth_param = f"--depth {depth}" if depth > 0 else ""
        # The 'git clone' command is executed in FILE_IO_DIR, so 'repo_name' is a relative path within it.
        command = f"git clone {depth_param} {repo_url} {repo_name}"

        result = execute_shell_command(command, timeout=timeout)

        # --- Error Handling (unchanged) ---
        if "fatal: repository" in result and "not found" in result:
             return f"Error: The clone failed because the repository at '{repo_url}' was not found. Please check the URL for typos."
        if "fatal: could not read Username" in result:
             return f"Error: The clone failed due to an authentication issue. The repository '{repo_url}' is likely private or requires login."
        if "Exit Code: 0" not in result and not os.path.exists(os.path.join(safe_clone_path, '.git')):
             return f"Error: Failed to clone repository for an unknown reason. Command output:\n\n{result}"

        return f"Success: Cloned repository to '{repo_name}'.\n\n{result}"

    except Exception as e:
        return f"An unexpected error occurred during clone operation. Reason: {e}"

# --- Composite Tools (The "Smart" Tools for the LLM) ---

def find_and_clone_repository(project_name: str) -> str:
    """
    A composite tool that searches GitHub for a project and clones the top result.
    This is the best tool for getting a public project's source code.
    """
    print(f"--- [Alice/GitHub-Composite] --- Finding and cloning '{project_name}'.")

    # Step 1: Search for the repository
    search_result_str = search_repositories(query=project_name, limit=1)
    if search_result_str.startswith("Error:") or search_result_str.startswith("No repositories"):
        return f"Could not find a repository for '{project_name}'. Search result: {search_result_str}"

    try:
        search_results = json.loads(search_result_str)
        if not search_results:
            return f"No repositories found for '{project_name}'."

        top_result = search_results[0]
        repo_url = top_result['url']
        print(f"--- [Alice/GitHub-Composite] --- Found top result: {repo_url}")

        # Step 2: Clone the repository
        return clone_repository(repo_url)

    except (json.JSONDecodeError, IndexError, KeyError) as e:
        return f"Error processing search results: {e}. Raw result: {search_result_str}"


def get_project_overview(owner: str, repo: str) -> str:
    """
    Provides a summary of a GitHub repository without cloning it, including its
    description, main language, last update, and root file structure.
    """
    print(f"--- [Alice/GitHub-Composite] --- Getting overview for {owner}/{repo}")

    repo_url = _get_api_url(f"/repos/{owner}/{repo}")
    contents_url = _get_api_url(f"/repos/{owner}/{repo}/contents/")

    try:
        # Get main repository details
        response = requests.get(repo_url, headers=_get_auth_headers(), timeout=10)

        # --- NEW ERROR HANDLING BLOCK ---
        if response.status_code == 404:
            return f"Error: A repository for '{owner}/{repo}' was not found (404). The owner or repository name is likely incorrect. You should try searching for the repository first."

        # Raise an exception for other bad statuses (500, 403, etc.)
        response.raise_for_status()
        repo_data = response.json()

        # Get repository contents
        contents_response = requests.get(contents_url, headers=_get_auth_headers(), timeout=10)
        contents_response.raise_for_status()
        contents_data = contents_response.json()

        # Step 2: Format the overview
        overview = (
            f"Overview for {repo_data['full_name']}:\n"
            f"Description: {repo_data.get('description', 'N/A')}\n"
            f"Language: {repo_data.get('language', 'N/A')}\n"
            f"Stars: {repo_data.get('stargazers_count', 0)}\n"
            f"Last Push: {repo_data.get('pushed_at', 'N/A')}\n\n"
            f"Root Contents:\n"
        )
        for item in contents_data:
            item_type = "dir" if item['type'] == 'dir' else "file"
            overview += f"- [{item_type}] {item['name']}\n"

        return overview

    except requests.exceptions.Timeout:
        return f"Error: The request to the GitHub API timed out. The service may be slow or your network connection may be unstable."
    except requests.exceptions.RequestException as e:
        return f"Error: A network issue occurred while trying to fetch the repository overview. The repository may not exist or GitHub may be unreachable. Reason: {e}"

def commit_and_push_changes(repo_directory: str, commit_message: str, branch: str = "main") -> str:
    """
    A composite tool that stages all changes, commits them with a message, and pushes to a branch.
    This should be used for committing work to one of the user's repositories.
    """
    print(f"--- [Alice/GitHub-Composite] --- Committing to '{repo_directory}' with message: '{commit_message}'")

    if not GITHUB_USERNAME or not GITHUB_API_KEY:
        return "Error: This tool requires GITHUB_USERNAME and GITHUB_API_KEY to be set for authentication."

    # Use the new function to get a safe, absolute path to the repository directory.
    safe_repo_path = _resolve_and_validate_path(repo_directory)

    if not safe_repo_path:
        return f"Error: The path '{repo_directory}' is invalid or outside the allowed directory."

    if not os.path.isdir(os.path.join(safe_repo_path, '.git')):
        return f"Error: '{repo_directory}' is not a valid git repository."

    # Execute commands from within the repo's directory
    original_cwd = os.getcwd()
    try:
        # Change to the validated, absolute path
        os.chdir(safe_repo_path)

        # --- Git commands (unchanged) ---
        add_result = execute_shell_command("git add .")
        if "fatal:" in add_result:
            return f"Error during 'git add':\n{add_result}"

        # Step 2: Commit
        commit_cmd = f'git commit -m "{commit_message}"'
        commit_result = execute_shell_command(commit_cmd)
        if "nothing to commit" in commit_result:
            return "Info: No changes to commit."
        if "fatal:" in commit_result:
            return f"Error during 'git commit':\n{commit_result}"

        # Step 3: Push
        # Note: Proper auth setup (e.g., git-credential-helper) is assumed for non-public repos.
        push_cmd = f"git push origin {branch}"
        push_result = execute_shell_command(push_cmd)

        final_report = (
            "Commit and Push Workflow Report:\n"
            f"--- Git Add ---\n{add_result}\n\n"
            f"--- Git Commit ---\n{commit_result}\n\n"
            f"--- Git Push ---\n{push_result}"
        )
        return final_report

    finally:
        os.chdir(original_cwd) # Always change back to the original directory
# --- Tool Definitions ---

def get_mapping():

    return {
        # Composite Tools
        "github.find_and_clone": find_and_clone_repository,
        "github.get_overview": get_project_overview,
        "github.commit_and_push": commit_and_push_changes,
        # Lower-Level Tools
        "github.list_my_repositories": list_my_repositories, # This now handles all list views
        "github.search": search_repositories,
        "github.clone": clone_repository,
    }
