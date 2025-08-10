
import requests
from ._base import SUMMARIZATION_MODEL,OLLAMA_URL


def summarize_text(text: str, length: str = "paragraph") -> str:
    """Takes a long piece of text and returns a concise summary."""
    print(f"--- [Alice/Content-Summarize] --- Summarizing text of length {len(text)}.")
    if not text.strip(): return "Error: Cannot summarize empty text."
    length_instructions = {"sentence": "in a single, concise sentence", "paragraph": "in a concise paragraph",
                           "bullet_points": "as a short list of bullet points"}
    instruction = length_instructions.get(length, length_instructions["paragraph"])
    system_prompt = f"You are a highly skilled summarization engine. Your task is to provide a clear and concise summary of the following text {instruction}. Respond only with the summary itself."
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={"model": SUMMARIZATION_MODEL,
                  "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": text}],
                  "stream": False},
            timeout=120
        )
        # --- NEW FOCUSED ERROR HANDLING ---
        if response.status_code == 404:
            return f"Error: The summarization model '{SUMMARIZATION_MODEL}' was not found by the Ollama service. Please check the model name."

        response.raise_for_status()
        return response.json().get('message', {}).get('content', "Error: No content from summarizer.")

    except requests.exceptions.ConnectionError:
        return f"Error: Could not connect to the Ollama service at '{OLLAMA_URL}'. Please ensure the service is running."
    except requests.exceptions.Timeout:
        return f"Error: The summarization request timed out. The model may be too slow or the input text too long."
    except Exception as e:
        return f"Error: Failed to summarize text. Reason: {e}"




def get_mapping():
    return {
        "content.summarize": summarize_text,  # Takes a long text and returns a concise summary.
    }