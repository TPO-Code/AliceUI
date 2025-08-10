import re

import markdown
import sys
import os
from PySide6.QtCore import Qt, QObject, Slot, QUrl
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout,
    QPushButton, QHBoxLayout, QMainWindow, QLineEdit, QFileDialog, QStyle
)
from PySide6.QtWebEngineCore import QWebEngineSettings, QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import Qt, QTimer, QThread, QObject, Signal

# --- ENHANCED BRIDGE FOR JAVASCRIPT TO CALL PYTHON ---
class JsBridge(QObject):
    """A more generic bridge for JS to call Python functions."""

    @Slot(str)
    def copyToClipboard(self, text):
        QApplication.clipboard().setText(text)
        print("Code copied to clipboard!")


# --- OPEN EXTERNAL LINKS IN SYSTEM BROWSER ---
class CustomWebEnginePage(QWebEnginePage):
    """
    Custom WebEnginePage to intercept navigation requests and open
    external links in the user's default browser.
    """

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        if nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked and url.scheme() in ['http', 'https']:
            QDesktopServices.openUrl(url)
            return False  # Prevent the view from navigating
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)


# --- THE SELF-CONTAINED MARKDOWN VIEWER COMPONENT ---
class MarkdownViewerWidget(QWidget):
    """
    A self-contained, feature-rich Markdown viewer component that inherits from
    QWidget. It includes its own layout and a full toolbar for enhanced functionality.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # --- Store raw markdown for the copy feature ---
        self.raw_markdown_text = ""

        # --- Create Widgets ---
        self._create_toolbar()
        self.web_view = QWebEngineView()

        # --- Configure Web View ---
        self.web_view.setPage(CustomWebEnginePage(self))
        self.web_view.page().setBackgroundColor(Qt.GlobalColor.transparent)
        self.web_view.setContextMenuPolicy(Qt.NoContextMenu)
        settings = self.web_view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled, True)

        # --- Configure WebChannel for Python-JS communication ---
        self.channel = QWebChannel(self.web_view.page())
        self.bridge = JsBridge(self)
        self.channel.registerObject("jsBridge", self.bridge)
        self.web_view.page().setWebChannel(self.channel)

        # --- Setup Layout ---
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self.toolbar)
        # Give a stretch factor of 1 to the web view, so it takes all available
        # vertical space, leaving the toolbar at its ideal height.
        main_layout.addWidget(self.web_view, 1)

        # --- CSS Definitions ---
        self._define_css_styles()

    def _create_toolbar(self):
        """Creates the main toolbar with controls on the left and search on the right."""
        self.toolbar = QWidget()
        # The layout is created but not yet set on the toolbar
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setContentsMargins(4, 4, 4, 4)
        toolbar_layout.setSpacing(5)

        self.toolbar.setStyleSheet("""
            QWidget {
                background-color: #282a36; 
                border-bottom: 1px solid #44475a;
            }
            QPushButton {
                background-color: #44475a; color: #f8f8f2; border: 1px solid #6272a4;
                padding: 4px; border-radius: 4px;
            }
            QPushButton:hover { background-color: #6272a4; }
            QPushButton:pressed { background-color: #3a3d4e; }
            QLineEdit {
                background-color: #44475a; color: #f8f8f2; border: 1px solid #6272a4;
                padding: 4px; border-radius: 4px;
            }
            QLineEdit:focus { border: 1px solid #bd93f9; }
        """)

        style = self.style()

        # --- Group 1: Action Buttons (aligned to the left) ---
        self.toggle_nav_button = QPushButton()
        self.toggle_nav_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_TitleBarMenuButton))
        self.toggle_nav_button.setFixedSize(30, 30)
        self.toggle_nav_button.setToolTip("Show/Hide Table of Contents")
        self.toggle_nav_button.clicked.connect(self.toggle_navigation_panel)
        toolbar_layout.addWidget(self.toggle_nav_button)

        self.theme_button = QPushButton()
        self.theme_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DesktopIcon))
        self.theme_button.setFixedSize(30, 30)
        self.theme_button.setToolTip("Switch between light and dark themes")
        self.theme_button.clicked.connect(self.toggle_theme)
        toolbar_layout.addWidget(self.theme_button)

        toolbar_layout.addSpacing(15)

        self.zoom_out_button = QPushButton()
        self.zoom_out_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowDown))
        self.zoom_out_button.setFixedSize(30, 30)
        self.zoom_out_button.setToolTip("Decrease text size (Zoom Out)")
        self.zoom_out_button.clicked.connect(self.zoom_out)
        toolbar_layout.addWidget(self.zoom_out_button)

        self.zoom_reset_button = QPushButton()
        self.zoom_reset_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        self.zoom_reset_button.setFixedSize(30, 30)
        self.zoom_reset_button.setToolTip("Reset text size to default")
        self.zoom_reset_button.clicked.connect(self.reset_zoom)
        toolbar_layout.addWidget(self.zoom_reset_button)

        self.zoom_in_button = QPushButton()
        self.zoom_in_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowUp))
        self.zoom_in_button.setFixedSize(30, 30)
        self.zoom_in_button.setToolTip("Increase text size (Zoom In)")
        self.zoom_in_button.clicked.connect(self.zoom_in)
        toolbar_layout.addWidget(self.zoom_in_button)

        self.pdf_button = QPushButton()
        self.pdf_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self.pdf_button.setFixedSize(30, 30)
        self.pdf_button.setToolTip("Export the current view to a PDF file")
        self.pdf_button.clicked.connect(self.print_to_pdf)
        toolbar_layout.addWidget(self.pdf_button)

        # --- NEW: Copy Markdown Button ---
        self.copy_md_button = QPushButton()
        self.copy_md_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_FileLinkIcon))
        self.copy_md_button.setFixedSize(30, 30)
        self.copy_md_button.setToolTip("Copy the full Markdown source to the clipboard")
        self.copy_md_button.clicked.connect(self.copy_markdown_to_clipboard)
        toolbar_layout.addWidget(self.copy_md_button)

        # --- THE MAGIC SPACER ---
        # This stretch will consume all available space between the left and right groups.
        toolbar_layout.addStretch()

        # --- Group 2: Search Controls (aligned to the right) ---
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search...")
        self.search_input.setFixedWidth(180)
        self.search_input.setFixedHeight(28)
        self.search_input.textChanged.connect(self.search_text)
        self.search_input.returnPressed.connect(self.find_next)
        toolbar_layout.addWidget(self.search_input)

        self.find_prev_button = QPushButton()
        self.find_prev_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowLeft))
        self.find_prev_button.setFixedSize(30, 30)
        self.find_prev_button.setToolTip("Find previous occurrence")
        self.find_prev_button.clicked.connect(self.find_prev)
        toolbar_layout.addWidget(self.find_prev_button)

        self.find_next_button = QPushButton()
        self.find_next_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowRight))
        self.find_next_button.setFixedSize(30, 30)
        self.find_next_button.setToolTip("Find next occurrence")
        self.find_next_button.clicked.connect(self.find_next)
        toolbar_layout.addWidget(self.find_next_button)

        # Finally, apply the layout to the toolbar widget
        self.toolbar.setLayout(toolbar_layout)

    def _define_css_styles(self):
        """Helper method to hold all CSS strings."""
        # NOTE: All CSS definitions are unchanged and included for completeness.
        self.styling_css = """
        :root {
            --bg-color: #282a36; --text-color: #f8f8f2; --header-color: #bd93f9;
            --link-color: #8be9fd; --border-color: #44475a; --quote-bg-color: #343746;
            --quote-border-color: #6272a4; --inline-code-bg: #44475a; --inline-code-text: #50fa7b;
            --code-block-bg: #21222C; --code-title-bg: #191a21; --code-lineno-bg: #282a36;
            --code-lineno-text: #6272a4;
        }
        body.light-theme {
            --bg-color: #ffffff; --text-color: #24292e; --header-color: #0366d6;
            --link-color: #0366d6; --border-color: #e1e4e8; --quote-bg-color: #f6f8fa;
            --quote-border-color: #dfe2e5; --inline-code-bg: rgba(27,31,35,.05);
            --inline-code-text: #24292e; --code-block-bg: #f6f8fa; --code-title-bg: #e1e4e8;
            --code-lineno-bg: #ffffff; --code-lineno-text: #959da5;
        }
        body {
            background-color: var(--bg-color); color: var(--text-color);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            line-height: 1.6; padding-left: 300px; padding-right: 20px;
            transition: background-color 0.2s, color 0.2s, padding-left 0.3s ease-in-out;
        }
        body.nav-hidden { padding-left: 20px; }
        h1,h2,h3,h4,h5,h6 {
            color: var(--header-color); border-bottom: 1px solid var(--border-color);
            padding-bottom: 5px; margin-top: 24px; margin-bottom: 16px; scroll-margin-top: 10px;
        }
        a { color: var(--link-color); text-decoration: none; }
        blockquote {
            background-color: var(--quote-bg-color); border-left: 4px solid var(--quote-border-color);
            padding: 10px 15px; margin: 0 0 16px; border-radius: 8px;
        }
        p > code, li > code {
            background-color: var(--inline-code-bg); color: var(--inline-code-text);
            padding: 0.2em 0.4em; border-radius: 4px;
        }
        """
        self.toc_css = """
        #toc {
            position: fixed; top: 0; left: 0; width: 260px; height: 100vh; padding: 20px;
            overflow-y: auto; border-right: 1px solid var(--border-color);
            background-color: var(--bg-color);
            transition: background-color 0.2s, border-color 0.2s, transform 0.3s ease-in-out;
            transform: translateX(0);
        }
        body.nav-hidden #toc { transform: translateX(-100%); }
        #toc .toc-title { font-weight: bold; color: var(--header-color); font-size: 1.2em; margin-bottom: 10px; }
        #toc ul { padding-left: 20px; list-style-type: none; }
        #toc ul li a { display: block; padding: 4px 0; color: var(--text-color); }
        #toc ul li a:hover { color: var(--link-color); }
        #toc ul li a.active { color: var(--link-color); font-weight: bold; }
        #toc ul li a .header-link {
            visibility: hidden;
            margin-left: 5px;
            color: var(--link-color);
            font-family: monospace;
        }
        #toc ul li a:hover .header-link { visibility: visible; }
        """
        self.code_block_css = """
        div.codehilite {
            background-color: var(--code-block-bg); border: 1px solid var(--border-color);
            border-radius: 8px; margin: 20px 0; overflow: hidden;
        }
        .code-title {
            display: flex; justify-content: space-between; align-items: center;
            background-color: var(--code-title-bg); padding: 8px 15px;
            font-family: "Fira Code", monospace; font-size: 0.85em; color: var(--header-color);
            border-bottom: 1px solid var(--border-color); cursor: pointer; user-select: none;
        }
        .code-content {
            display: grid; grid-template-rows: 1fr;
            transition: grid-template-rows 0.3s ease-in-out;
        }
        .code-collapsed .code-content { grid-template-rows: 0fr; }
        .code-content > div { overflow: hidden; }
        div.codehilite table { width: 100%; border-collapse: collapse; font-family: "Fira Code", monospace; }
        td.linenos {
            color: var(--code-lineno-text); padding: 0.8em; text-align: right;
            user-select: none; border-right: 1px solid var(--border-color);
            background-color: var(--code-lineno-bg);
        }
        td.code { padding: 0; }
        td.code pre { margin: 0; padding: 0.8em; line-height: 1.5; }
        """
        self.admonition_css = """
        /* --- Admonition Styles --- */
        .admonition {
            padding: 15px; margin-bottom: 20px; border-left: 6px solid;
            border-radius: 8px; background-color: var(--quote-bg-color);
        }
        .admonition-title {
            margin: -15px -15px 15px -15px; padding: 10px 15px; font-weight: bold;
            border-top-left-radius: 8px; border-top-right-radius: 8px; color: var(--bg-color);
        }
        .admonition.note { border-color: #448aff; }
        .admonition.note > .admonition-title { background-color: #448aff; }
        .admonition.warning { border-color: #ff9800; }
        .admonition.warning > .admonition-title { background-color: #ff9800; }
        .admonition.danger { border-color: #f44336; }
        .admonition.danger > .admonition-title { background-color: #f44336; }
        .admonition.tip { border-color: #00bcd4; }
        .admonition.tip > .admonition-title { background-color: #00bcd4; }
        details { margin-bottom: 20px; }
        details > summary { cursor: pointer; font-weight: bold; }
        """
        self.code_theme_css = """
        .codehilite .c{color:#6272a4}.codehilite .k{color:#ff79c6}.codehilite .n{color:#f8f8f2}.codehilite .o{color:#ff79c6}.codehilite .p{color:#f8f8f2}.codehilite .cm{color:#6272a4}.codehilite .cp{color:#ff79c6}.codehilite .c1{color:#6272a4}.codehilite .cs{color:#ff79c6}.codehilite .kc{color:#ff79c6}.codehilite .kd{color:#8be9fd;font-style:italic}.codehilite .kn{color:#ff79c6}.codehilite .kp{color:#ff79c6}.codehilite .kr{color:#ff79c6}.codehilite .kt{color:#8be9fd}.codehilite .m{color:#bd93f9}.codehilite .s{color:#f1fa8c}.codehilite .na{color:#50fa7b}.codehilite .nb{color:#f8f8f2}.codehilite .nc{color:#50fa7b;font-weight:700}.codehilite .no{color:#bd93f9}.codehilite .nd{color:#ff79c6}.codehilite .nf{color:#50fa7b}.codehilite .nv{color:#8be9fd;font-style:italic}.codehilite .s2{color:#f1fa8c}.codehilite .se{color:#bd93f9}.codehilite .si{color:#f1fa8c}
        body.light-theme .codehilite .c{color:#6a737d}.body.light-theme .codehilite .k{color:#d73a49}.body.light-theme .codehilite .n{color:#24292e}.body.light-theme .codehilite .o{color:#d73a49}.body.light-theme .codehilite .p{color:#24292e}.body.light-theme .codehilite .cm{color:#6a737d}.body.light-theme .codehilite .cp{color:#d73a49}.body.light-theme .codehilite .c1{color:#6a737d}.body.light-theme .codehilite .cs{color:#d73a49}.body.light-theme .codehilite .kc{color:#d73a49}.body.light-theme .codehilite .kd{color:#d73a49}.body.light-theme .codehilite .kn{color:#d73a49}.body.light-theme .codehilite .kp{color:#d73a49}.body.light-theme .codehilite .kr{color:#d73a49}.body.light-theme .codehilite .kt{color:#d73a49}.body.light-theme .codehilite .m{color:#005cc5}.body.light-theme .codehilite .s{color:#032f62}.body.light-theme .codehilite .na{color:#005cc5}.body.light-theme .codehilite .nb{color:#005cc5}.body.light-theme .codehilite .nc{color:#6f42c1;font-weight:700}.body.light-theme .codehilite .no{color:#005cc5}.body.light-theme .codehilite .nd{color:#6f42c1}.body.light-theme .codehilite .nf{color:#6f42c1}.body.light-theme .codehilite .nv{color:#e36209}.body.light-theme .codehilite .s2{color:#032f62}.body.light-theme .codehilite .se{color:#032f62}.body.light-theme .codehilite .si{color:#032f62}
        """

    @Slot()
    def toggle_navigation_panel(self):
        self.web_view.page().runJavaScript("toggleNav();")

    @Slot()
    def toggle_theme(self):
        js_code = """
        document.body.classList.toggle('light-theme');
        if (typeof mermaid !== 'undefined') { initializeMermaid(); }
        """
        self.web_view.page().runJavaScript(js_code)

    @Slot()
    def zoom_in(self):
        self.web_view.setZoomFactor(self.web_view.zoomFactor() + 0.1)

    @Slot()
    def zoom_out(self):
        self.web_view.setZoomFactor(self.web_view.zoomFactor() - 0.1)

    @Slot()
    def reset_zoom(self):
        self.web_view.setZoomFactor(1.0)

    @Slot(str)
    def search_text(self, text):
        if text:
            self.web_view.page().findText(text, self._handle_find_result)
        else:
            self.web_view.page().findText("")
            self.search_input.setStyleSheet("")

    @Slot()
    def find_next(self):
        text = self.search_input.text()
        if text:
            self.web_view.page().findText(text, self._handle_find_result)

    @Slot()
    def find_prev(self):
        text = self.search_input.text()
        if text:
            self.web_view.page().findText(text, QWebEnginePage.FindFlag.FindBackward, self._handle_find_result)

    @Slot(bool)
    def _handle_find_result(self, found):
        """Callback for findText to update UI based on result."""
        if self.search_input.text():
            if found:
                # Use a less intrusive success indicator
                self.search_input.setStyleSheet("border: 1px solid #50fa7b;")
            else:
                # Use red to indicate not found
                self.search_input.setStyleSheet("border: 1px solid #ff5555; background-color: #552222;")

    @Slot()
    def print_to_pdf(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save as PDF", "", "PDF Files (*.pdf)"
        )
        if file_path:
            self.web_view.page().printToPdf(file_path)
            print(f"Saved PDF to {file_path}")

    @Slot()
    def copy_markdown_to_clipboard(self):
        """Copies the raw Markdown source text to the system clipboard."""
        if self.raw_markdown_text:
            QApplication.clipboard().setText(self.raw_markdown_text)
            print("Full Markdown source copied to clipboard!")
        else:
            print("No Markdown content to copy.")

    def correct_markdown_indentation(self,markdown_text: str) -> str:
        """
        Corrects common Markdown indentation errors made by LLMs, where sub-items
        are not indented under their parent correctly.

        The heuristic works by assuming that if a numbered list item ends in a
        colon, any immediately following bulleted list items should be nested
        under it as a sub-list.

        Args:
            markdown_text: A string containing the Markdown text to be corrected.

        Returns:
            A string containing the corrected Markdown text.
        """
        lines = markdown_text.splitlines()
        new_lines = []
        is_in_sublist_context = False
        indentation = '    '  # A standard 4-space indent

        # Pattern to identify any list item (*, -, or 1.)
        any_list_item_pattern = re.compile(r'^\s*([\*\-]|\d+\.)\s+')
        # Pattern to specifically identify a numbered list item (e.g., "1.", "2.")
        numbered_list_item_pattern = re.compile(r'^\s*\d+\.\s+')

        for line in lines:
            trimmed_line = line.strip()

            # A blank line resets all context.
            if not trimmed_line:
                is_in_sublist_context = False
                new_lines.append(line)
                continue

            is_any_list_item = bool(any_list_item_pattern.match(line))
            is_numbered_item = bool(numbered_list_item_pattern.match(line))

            # --- REVISED CORE LOGIC ---

            # 1. Decide if we should EXIT the sublist context.
            #    If the current line is a numbered item, it's a new parent/sibling,
            #    so we are no longer in a sublist of a previous item.
            if is_numbered_item:
                is_in_sublist_context = False

            # 2. Decide if the current line should be indented.
            #    We indent if we are in a sublist context AND the line is a list item.
            if is_in_sublist_context and is_any_list_item:
                new_lines.append(indentation + line.lstrip())
            else:
                # Otherwise, add the line as-is.
                new_lines.append(line)

            # 3. Decide if the NEXT line should start a sublist context.
            #    A numbered item ending with a colon starts a sublist context.
            if is_numbered_item and trimmed_line.endswith(':'):
                is_in_sublist_context = True

        return '\n'.join(new_lines)


    def setMarkdown(self, text: str, base_url: QUrl = None):
        """Converts Markdown to HTML and loads it into the web view."""
        text=self.correct_markdown_indentation(text)
        self.raw_markdown_text = text  # Store the raw markdown text

        if base_url is None:
            base_url = QUrl()  # Use an empty URL if none is provided

        md = markdown.Markdown(
            extensions=[
                'tables', 'toc', 'admonition', 'pymdownx.details',
                'pymdownx.arithmatex', 'pymdownx.superfences', 'pymdownx.highlight'
            ],
            extension_configs={
                'toc': {'title': 'Table of Contents', 'permalink': False},
                'pymdownx.arithmatex': {'generic': True},
                'pymdownx.superfences': {
                    'custom_fences': [{'name': 'mermaid', 'class': 'mermaid',
                                       'format': lambda src, *args, **kwargs: f'<pre class="mermaid">{src}</pre>'}]
                },
                'pymdownx.highlight': {'linenums': True, 'css_class': 'codehilite', 'guess_lang': False}
            }
        )
        md_html = md.convert(text)
        toc_html = md.toc

        full_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
            <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>
            <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js"></script>
            <script type="text/javascript" src="qrc:///qtwebchannel/qwebchannel.js"></script>
            <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
            <style>
                {self.styling_css} {self.toc_css} {self.code_block_css}
                {self.code_theme_css} {self.admonition_css}
            </style>
        </head>
        <body>
            <nav id="toc">{toc_html}</nav>
            <main>{md_html}</main>
            <script>
                var jsBridge;
                new QWebChannel(qt.webChannelTransport, (channel) => {{
                    jsBridge = channel.objects.jsBridge;
                }});

                function initializeMermaid() {{
                    try {{
                        const isLightTheme = document.body.classList.contains('light-theme');
                        mermaid.initialize({{
                            startOnLoad: false, theme: isLightTheme ? 'default' : 'dark',
                            securityLevel: 'loose'
                        }});
                        mermaid.run({{ nodes: document.querySelectorAll('pre.mermaid') }});
                    }} catch (e) {{ console.error("Mermaid rendering failed:", e); }}
                }}

                document.addEventListener('DOMContentLoaded', function() {{
                    renderMathInElement(document.body, {{
                        delimiters: [ {{left: '$$', right: '$$', display: true}}, {{left: '$', right: '$', display: false}} ]
                    }});
                    initializeMermaid();
                }});

                function toggleNav() {{ document.body.classList.toggle('nav-hidden'); }}

                document.querySelectorAll('div.codehilite').forEach((block) => {{
                    const titleBar = document.createElement('div');
                    titleBar.className = 'code-title';
                    const preTag = block.querySelector('pre');
                    let language = 'code';
                    if (preTag && preTag.className) {{
                         const langClass = Array.from(preTag.classList).find(c => !['highlight'].includes(c));
                         if (langClass) {{ language = langClass; }}
                    }}
                    titleBar.innerHTML = `<span>${{language}}</span><button class="copy-btn">Copy</button>`;
                    block.insertBefore(titleBar, block.firstChild);

                    const contentWrapper = document.createElement('div');
                    contentWrapper.className = 'code-content';
                    const table = block.querySelector('table');
                    if (table) {{
                        const innerDiv = document.createElement('div');
                        innerDiv.appendChild(table);
                        contentWrapper.appendChild(innerDiv);
                        block.appendChild(contentWrapper);
                    }}

                    titleBar.addEventListener('click', (e) => {{
                        if (e.target.tagName !== 'BUTTON') block.classList.toggle('code-collapsed');
                    }});

                    titleBar.querySelector('.copy-btn').addEventListener('click', (e) => {{
                        e.stopPropagation();
                        const codeToCopy = block.querySelector('td.code').innerText.trimEnd();
                        if (jsBridge) {{
                            jsBridge.copyToClipboard(codeToCopy);
                            e.target.innerText = 'Copied!';
                            setTimeout(() => {{ e.target.innerText = 'Copy'; }}, 2000);
                        }}
                    }});
                }});

                const tocLinks = document.querySelectorAll('#toc a');
                const headings = Array.from(tocLinks).map(link => {{
                    const id = decodeURIComponent(link.getAttribute('href').substring(1));
                    return document.getElementById(id);
                }}).filter(Boolean);

                window.addEventListener('scroll', () => {{
                    let current = '';
                    const scrollY = window.scrollY + 20;
                    for (const heading of headings) {{
                        if (heading.offsetTop <= scrollY) current = heading.getAttribute('id');
                    }}
                    tocLinks.forEach(link => {{
                        link.classList.remove('active');
                        if (decodeURIComponent(link.getAttribute('href').substring(1)) === current) {{
                            link.classList.add('active');
                        }}
                    }});
                }}, {{ passive: true }});
            </script>
        </body>
        </html>
        """
        self.web_view.setHtml(full_html, baseUrl=base_url)

    def clear(self):
        """Clears the content of the viewer."""
        self.setMarkdown("")


# --- Test application ---
if __name__ == "__main__":

    # Create a test.md file if it doesn't exist for demonstration
    markdown_file = "../../test.md"
    if not os.path.exists(markdown_file):
        with open(markdown_file, "w", encoding="utf-8") as f:
            f.write("# Hello, Markdown!\n\nThis is a demo of the **enhanced** Markdown Viewer.\n\n"
                    "## Features\n\n*   Theme Toggling\n*   Zoom Controls\n*   In-page Search\n\n"
                    "![A local image placeholder](./placeholder.png)\n*This image won't load unless you create `placeholder.png`*\n")

    markdown_text = open(markdown_file, "r", encoding="utf-8").read()


    class MainWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Enhanced Markdown Viewer")
            self.setGeometry(100, 100, 1200, 800)

            markdown_viewer = MarkdownViewerWidget()
            self.setCentralWidget(markdown_viewer)

            # --- Load markdown with base_path for local image support ---
            base_path = os.path.dirname(os.path.abspath(markdown_file))
            markdown_viewer.setMarkdown(markdown_text)


    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())