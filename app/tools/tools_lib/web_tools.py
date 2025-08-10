import requests
from bs4 import BeautifulSoup
from googlesearch import search
from requests.exceptions import HTTPError

def search_web(query: str, num_results: int = 5) -> str:
    """Performs a web search using the 'googlesearch-python' library and returns a list of URLs."""
    # ... (implementation is unchanged)
    print(f"--- [Alice/Search-Web] --- {query}")
    if not query: return "Error: Search query cannot be empty."
    try:
        results_list = list(search(query, num_results=num_results, lang="en", timeout=2.0))
        if not results_list: return "No results found. It's possible Google blocked the request."
        formatted_output = [f"Here are the top {len(results_list)} URLs for '{query}':\n"]
        formatted_output.extend(results_list)
        return "\n".join(formatted_output)
    except HTTPError as e: return f"Error: Google actively blocked this request. HTTP Error: {e}"
    except Exception as e: return f"An unexpected error occurred during the search: {e}"


def extract_text_from_url(url: str, max_length: int = 4000) -> str:
    """Fetches content from a URL, parses HTML, and extracts clean, readable text."""
    print(f"--- [Alice/URL-Text] --- : {url}")
    if not url or not url.startswith(
        ('http://', 'https://')): return "Error: Invalid URL provided. It must start with http:// or https://."
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    try:
        response = requests.get(url, headers=headers, timeout=15)

        # --- NEW FOCUSED ERROR HANDLING ---
        if response.status_code == 404:
            return f"Error: The content at the URL was not found (404 Error). The link is likely broken or the page has been moved."
        if response.status_code == 403:
            return f"Error: Access to the content at the URL is forbidden (403 Error). The page may require a login or special permissions."
        if response.status_code >= 500:
            return f"Error: The server hosting the URL is having issues (Server Error {response.status_code}). Please try again later."

        # Raise an exception for other client-side error codes (e.g., 400, 401)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        for element in soup(["script", "style", 'nav', 'header', 'footer', 'aside', 'form']): element.decompose()
        text = soup.get_text(separator='\n', strip=True)
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        clean_text = '\n'.join(chunk for chunk in chunks if chunk)
        if not clean_text:
            return "Success: The URL was read, but it contained no readable text content after parsing."
        return clean_text[:max_length] + ("\n\n... (content truncated)" if len(clean_text) > max_length else "")

    except requests.exceptions.Timeout:
        return "Error: The request to the URL timed out. The server is slow to respond or the network is unstable."
    except requests.exceptions.RequestException as e:
        return f"Error: Could not fetch URL due to a network issue. The domain may not exist or your connection may be down. Reason: {e}"
    except Exception as e:
        return f"Error: An unexpected error occurred while processing the page. Reason: {e}"


def get_mapping():
    return {
        "web.read": extract_text_from_url,  # Extracts the clean, readable text content from a URL.
        "web.search": search_web,  # Performs a web search and returns a list of URLs.
    }