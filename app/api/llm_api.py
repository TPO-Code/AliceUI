import json
from typing import List

import requests
from PySide6.QtCore import QThread, Signal, Slot

from app.data.app_data import app_data
class SendMessageWorker(QThread):
    completed_ollama_call = Signal(str)

    def __init__(self,messages: str, model:str, options = None):
        super().__init__()
        self.messages = messages
        self.model = model
        self.options = options

    @Slot()
    def run(self):
        print("contacting ollama")
        result=query_ollama(self.messages, self.model, self.options)
        message_content = result.get('message', {}).get('content', '')
        self.completed_ollama_call.emit(message_content)

def query_ollama(messages, model:str, options = None):
    payload={
        "model":model,
        "messages":messages,
        "stream":False,
        "options":options
    }

    response=requests.post(app_data.get("settings.ollama.url","http://localhost:11434")+"/api/chat",json=payload)
    response.raise_for_status()
    print("ollama responded")
    return response.json()

class GetModelListWorker(QThread):
    completed_ollama_call = Signal(list)

    def __init__(self):
        super().__init__()

    @Slot()
    def run(self):
        print("contacting ollama")
        result=get_available_models()
        print(json.dumps(result))
        self.completed_ollama_call.emit(result)

def get_available_models():
    """Fetches the list of available models from the Ollama API."""
    try:
        response = requests.get(app_data.get("settings.ollama.url","http://localhost:11434")+"/api/tags")
        response.raise_for_status()
        models = response.json().get("models", [])
        return [model["name"] for model in models]
    except requests.exceptions.ConnectionError:
        message = "Error: Could not connect to Ollama. Is the server running?"
        print(message)
        return [message]
    except requests.exceptions.RequestException as e:
        message = f"Error: {e}"
        print(message)
        return [message]


