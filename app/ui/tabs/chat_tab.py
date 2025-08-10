import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QComboBox, QSplitter, QTextEdit, QHBoxLayout, QCheckBox

from app.api.llm_api import GetModelListWorker, SendMessageWorker
from app.data.colors import UIColors
from app.data.app_data import app_data
from app.ui.widgets.chat_text_input_widget import ChatTextInputWidget
from app.ui.widgets.chat_view_widget import ChatViewWidget


class ChatTab(QWidget):
    def __init__(self):
        super().__init__()
        app_data.set("messages", [])

        main_layout = QVBoxLayout()
        self.setLayout(main_layout)

        # --  Model selection and options  --
        options_layout=QHBoxLayout()
        self.model_selection = QComboBox()
        self.TTS_toggle =QCheckBox("Text To Speech")
        main_layout.addWidget(self.model_selection)
        main_layout.addWidget(self.TTS_toggle)
        options_layout.addWidget(self.model_selection)
        options_layout.addWidget(self.TTS_toggle)
        main_layout.addLayout(options_layout)

        splitter = QSplitter(Qt.Orientation.Vertical)

        main_layout.addWidget(splitter)
        # --  System prompt  --

        self.system_prompt = QTextEdit()
        self.system_prompt.setPlaceholderText("System Prompt")
        self.system_prompt.setStyleSheet(f"""
            QTextEdit{{
            margin: 8px;
            padding: 8px;
            border: 1px solid;
            border-color: {app_data.get('setting.theme.highlight_color', UIColors.highlight_color)};
            border-radius: 10px;
            background: {app_data.get('setting.theme.input_field_color', UIColors.input_field_color)};
            }}
            """
                                         )
        splitter.addWidget(self.system_prompt)

        # --  Chat view  --
        self.chat_view = ChatViewWidget()
        self.chat_view.setStyleSheet(f"""QWidget{{
            padding: 8px;
            border-radius: 10px;
            background: {app_data.get('setting.theme.input_field_color', UIColors.input_field_color)}
            }}
            """
                                     )
        splitter.addWidget(self.chat_view)

        # --   Input  ---
        self.input_field = ChatTextInputWidget()
        self.input_field.setStyleSheet(f"""
            QTextEdit{{
            margin: 8px;
            padding: 8px;
            border: 1px solid;
            border-color: {app_data.get('setting.theme.highlight_color', UIColors.highlight_color)};
            border-radius: 10px;
            background: {app_data.get('setting.theme.input_field_color', UIColors.input_field_color)}}}""")
        splitter.addWidget(self.input_field)

        splitter.setSizes([40, 3000, 40])

        # --  connections  --
        self.input_field.send_message.connect(self.send_message)

        self.get_model_list_worker = GetModelListWorker()
        self.get_model_list_worker.start()
        self.get_model_list_worker.completed_ollama_call.connect(self.got_model_list)

    def send_message(self, message: str):
        system_prompt = {
            "role": "system",
            "content": self.system_prompt.toPlainText()
        }

        messages = app_data.get("messages", [])
        new_message = {
            "role": "user",
            "content": message
        }
        messages.append(new_message)
        messages.insert(0, system_prompt)

        self.chat_view.add_message(message, True)
        self.input_field.setEnabled(False)

        print(json.dumps(messages, indent=4))
        self.allama_request_worker = SendMessageWorker(messages, self.model_selection.currentText())
        self.allama_request_worker.start()
        self.allama_request_worker.completed_ollama_call.connect(self.got_ollama_response)

    def got_ollama_response(self, result):
        print(result)
        messages = app_data.get("messages", [])
        new_message = {
            "role": "assistant",
            "content": result
        }
        messages.append(new_message)
        app_data.set("messages", messages)
        self.chat_view.add_message(result, False)
        self.input_field.setEnabled(True)

    def got_model_list(self, models: list):
        self.model_selection.addItems(models)