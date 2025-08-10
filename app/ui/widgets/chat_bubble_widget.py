
import re

import markdown

from PySide6.QtCore import Slot, QUrl, Qt, QTimer,QObject, Signal
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout,
    QPushButton, QHBoxLayout, QStyle, QFrame, QSizePolicy, QLabel
)
from PySide6.QtWebEngineCore import QWebEngineSettings, QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtGui import QDesktopServices

from app.utils.debug_logger import get_logger


def separate_thinking_tag_form_response(content: str):
    log=get_logger()
    think_start_tag, think_end_tag = "<think>", "</think>"
    clean_content = content.strip()
    log.debug(f"Parsing model response. Raw content length: {len(clean_content)}")
    if clean_content.startswith(think_start_tag):
        end_tag_pos = clean_content.find(think_end_tag)
        if end_tag_pos != -1:
            thought = clean_content[len(think_start_tag):end_tag_pos].strip()
            response = clean_content[end_tag_pos + len(think_end_tag):].strip()
            log.debug(f"Found thought block. Length: {len(thought)}")
            return thought, response
    log.debug("No thought block found in response.")
    return None, clean_content


class JsBridge(QObject):
    """A more generic bridge for JS to call Python functions."""
    geometry_update_requested = Signal()
    @Slot(str)
    def copyToClipboard(self, text):
        log = get_logger()
        QApplication.clipboard().setText(text)
        log.debug("Code copied to clipboard!")

    @Slot()
    def requestGeometryUpdate(self):
        """
        Called from JavaScript. Emits a signal to trigger a height adjustment
        in the main widget. A small timer prevents stuttering from rapid events.
        """
        QTimer.singleShot(15, self.geometry_update_requested.emit)

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

class BubbleMarkdownViewerWidget(QWidget):
    """
    A self-contained, feature-rich Markdown viewer component that inherits from
    QWidget. It includes its own layout and a full toolbar for enhanced functionality.
    """
    message_rendered = Signal(str)
    geometry_changed = Signal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self.log=get_logger()
        # --- Store raw markdown for the copy feature ---
        self.raw_markdown_text = ""

        # --- Create Widgets ---
        self._create_toolbar()
        self.web_view = QWebEngineView()

        # Remove default margins from the web view
        self.web_view.setContentsMargins(0, 0, 0, 0)

        # Configure Web View
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
        # Connect to loadFinished signal
        self.web_view.loadFinished.connect(self._on_load_finished)
        #self.bridge.geometry_update_requested.connect(self._adjust_height)
        self.bridge.geometry_update_requested.connect(self._on_geometry_update_requested)
        # Set initial minimum height
        self.setMinimumHeight(50)

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

    def _on_geometry_update_requested(self):
        self._adjust_height()
        self.geometry_changed.emit()

    def _on_load_finished(self, success):
        """Called when the web page has finished loading."""
        if success:
            # Use a timer to allow the page to fully render
            QTimer.singleShot(100, self._adjust_height)

            self.message_rendered.emit("success")

    def get_content_width(self, callback):
        """Get the actual width of the rendered content using JavaScript."""
        self.web_view.page().runJavaScript(
            """
            (function() {
                var body = document.body;
                var html = document.documentElement;
                var width = Math.max(
                    body.scrollWidth, body.offsetWidth,
                    html.clientWidth, html.scrollWidth, html.offsetWidth
                );
                return width;
            })()
            """,
            callback
        )

    def _adjust_height(self):
        """Adjust the widget height to fit the content."""
        # Get the content height using JavaScript
        self.web_view.page().runJavaScript(
            "document.body.scrollHeight",
            self._set_height_from_content
        )

    def _set_height_from_content(self, content_height):
        if content_height and content_height > 0:
            toolbar_height = self.toolbar.sizeHint().height() if not self.toolbar.isHidden() else 0
            total_height = content_height + toolbar_height + 10

            self.setFixedHeight(total_height)

            if self.parent():
                self.parent().updateGeometry()

            # 👇 notify the chat view that our height actually changed
            self.geometry_changed.emit()

    def _create_toolbar(self):
        """Creates the main toolbar with controls on the left and search on the right."""
        self.toolbar = QWidget()
        # The layout is created but not yet set on the toolbar
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setContentsMargins(4, 4, 4, 4)
        toolbar_layout.setSpacing(5)

        self.toolbar.setStyleSheet("""
            QWidget {
                border-bottom: 1px solid #44475a;
                background: transparent;
                padding: 4px; border-radius: 1px;
            }
            QPushButton {
                color: #f8f8f2; border: 0px;
                padding: 4px; border-radius: 4px;
            }
            QPushButton:hover { background-color: #6272a4; }
            QPushButton:pressed { background-color: #3a3d4e; }
        """)

        style = self.style()

        self.copy_md_button = QPushButton()
        self.copy_md_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_FileLinkIcon))
        self.copy_md_button.setFixedSize(30, 30)
        self.copy_md_button.setToolTip("Copy the full Markdown source to the clipboard")
        self.copy_md_button.clicked.connect(self.copy_markdown_to_clipboard)
        toolbar_layout.addStretch()
        toolbar_layout.addWidget(self.copy_md_button)


        self.toolbar.setLayout(toolbar_layout)

    def _define_css_styles(self):
        """Helper method to hold all CSS strings."""
        # NOTE: All CSS definitions are unchanged and included for completeness.
        self.styling_css = """
        :root {
          --text-color:#f8f8f2; --header-color:#bd93f9;
          --link-color:#8be9fd; --border-color:#44475a; --quote-bg-color:#343746;
          --quote-border-color:#6272a4; --inline-code-bg:#44475a; --inline-code-text:#50fa7b;
          --code-block-bg:#21222C; --code-title-bg:#191a21; --code-lineno-bg:#282a36;
          --code-lineno-text:#6272a4;
        }
        * { margin:0; padding:0; box-sizing:border-box; }
        
        html, body { margin:0; padding:0; height:auto; overflow:hidden; }  /* <-- closed properly */
        
        body {
          color:var(--text-color);
          font-family:-apple-system, BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
          line-height:1.4;
          padding:5px;
          word-break:break-word;
          overflow-wrap: break-word;
        }

        /* Let content define its own natural width; we clamp it in Qt */
        main {
          display: block;       /* fill the webview width */
          width: auto;
          max-width: 100%;      /* never exceed the bubble */
          white-space: normal;  /* wrap text normally */
        }

        p { margin:0 0 8px 0; }
        p:last-child { margin-bottom:0; }

        h1,h2,h3,h4,h5,h6 {
          color:var(--header-color);
          border-bottom:1px solid var(--border-color);
          padding-bottom:5px; margin-top:5px; margin-bottom:16px;
          scroll-margin-top:10px;
        }
        img { max-width:100%; height:auto; }
        a { color:var(--link-color); text-decoration:none; }
        blockquote {
          background-color:var(--quote-bg-color);
          border-left:4px solid var(--quote-border-color);
          padding:10px 15px; margin:0 0 16px; border-radius:8px;
        }
        p > code, li > code {
          background-color:var(--inline-code-bg); color:var(--inline-code-text);
          padding:0.2em 0.4em; border-radius:4px;
        }
        p, li { 
            white-space: normal; 
            overflow-wrap: break-word; 
            word-break: normal;
        }
        html.measure-mode body,
        html.measure-mode main,
        html.measure-mode p,
        html.measure-mode li,
        html.measure-mode blockquote,
        html.measure-mode pre,
        html.measure-mode code {
          max-width: none !important;
          overflow-wrap: normal !important;
          word-break: normal !important;
          white-space: nowrap !important;   /* <- critical */
        }
        """
        self.code_block_css = """
        div.codehilite {
          background-color: var(--code-block-bg);
          border: 1px solid var(--border-color);
          border-radius: 8px;
          margin: 20px 0;
          overflow: auto;     /* scroll if needed, don’t blow layout */
          max-width: 100%;    /* stay inside the bubble */
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
        div.codehilite table { 
            width: max-content;
            border-collapse: collapse;
            font-family: "Fira Code", monospace; }
        td.linenos {
            color: var(--code-lineno-text); padding: 0.8em; text-align: right;
            user-select: none; border-right: 1px solid var(--border-color);
            background-color: var(--code-lineno-bg);
        }
        td.code { padding: 0; }
        td.code pre { white-space: pre; }
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

    def copy_markdown_to_clipboard(self):
        """Copies the raw Markdown source text to the system clipboard."""
        if self.raw_markdown_text:
            QApplication.clipboard().setText(self.raw_markdown_text)
            self.log.debug("Full Markdown source copied to clipboard!")
        else:
            self.log.debug("No Markdown content to copy.")

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
        llm_thinking, llm_answer = separate_thinking_tag_form_response(text)
        llm_thinking_html=""
        if llm_thinking:
            llm_thinking_html=f"""
                <details>
                  <summary>Thoughts</summary>
                  <p>{llm_thinking}</p>
                </details><br>
            """
        self.raw_markdown_text = llm_answer  # Store the raw markdown text

        if base_url is None:
            base_url = QUrl()  # Use an empty URL if none is provided

        md = markdown.Markdown(
            extensions=[
                'tables', 'admonition', 'pymdownx.details',
                'pymdownx.arithmatex', 'pymdownx.superfences', 'pymdownx.highlight'
            ],
            extension_configs={
                'pymdownx.arithmatex': {'generic': True},
                'pymdownx.superfences': {
                    'custom_fences': [{'name': 'mermaid', 'class': 'mermaid',
                                       'format': lambda src, *args, **kwargs: f'<pre class="mermaid">{src}</pre>'}]
                },
                'pymdownx.highlight': {'linenums': True, 'css_class': 'codehilite', 'guess_lang': False}
            }
        )
        md_html = md.convert(llm_answer)

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
                {self.styling_css} {self.code_block_css}
                {self.code_theme_css} {self.admonition_css}
            </style>
        </head>
        <body>
            <main>
                {llm_thinking_html}
                {md_html}
            </main>
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
                    
                    document.querySelectorAll('details').forEach(detailsElement => {{
                        // The 'toggle' event fires whenever the element is opened or closed.
                        detailsElement.addEventListener('toggle', () => {{
                            if (jsBridge) {{
                                // Call back to Python to request a geometry update.
                                jsBridge.requestGeometryUpdate();
                            }}
                        }});
                    }});
                }});

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
            </script>
        </body>
        </html>
        """
        self.web_view.setHtml(full_html, baseUrl=base_url)

    def clear(self):
        """Clears the content of the viewer."""
        self.setMarkdown("")

class _BubbleWidget(QFrame):
    rendered = Signal(QWidget, bool)

    def __init__(self, text: str, *, is_user: bool, bg_color: str, alias_attr: str):
        super().__init__()
        self._sizing = False
        self._last_width = None
        self._is_user = is_user
        self.text_content = text

        self.setStyleSheet(f"""
        QFrame{{
            border-radius: 10px;
            padding: 6px;
            color: white;
            background-color: {bg_color};
        }}
        """)

        # Single markdown viewer; expose a legacy alias name for compatibility.
        self._viewer = BubbleMarkdownViewerWidget()
        setattr(self, alias_attr, self._viewer)   # user_message or llm_text

        self._viewer.setMarkdown(text)

        layout = QVBoxLayout()
        layout.addWidget(self._viewer)
        layout.addStretch()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.setLayout(layout)

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

        # When the webview finishes, bubble announces it's ready.
        self._viewer.message_rendered.connect(lambda _: self.rendered.emit(self, self._is_user))

    def adjust_width(self, max_allowed_width: int):
        if self._sizing:
            return
        self._sizing = True

        js = """
        (() => {
          const main = document.querySelector('main');
          if (!main) return 0;
          const root = document.documentElement;

          const prev = {
            width: main.style.width,
            maxWidth: main.style.maxWidth,
            display: main.style.display
          };

          // Measure with clamps/wrapping disabled
          root.classList.add('measure-mode');
          main.style.width = 'max-content';
          main.style.maxWidth = 'none';
          main.style.display = 'inline-block';

          const width = Math.ceil(main.scrollWidth || main.getBoundingClientRect().width);

          // Restore
          main.style.width = prev.width;
          main.style.maxWidth = prev.maxWidth;
          main.style.display = prev.display;
          root.classList.remove('measure-mode');

          return width;
        })()
        """

        self._viewer.web_view.page().runJavaScript(
            js, lambda w: self._apply_width_constraint(w, max_allowed_width)
        )

    def _apply_width_constraint(self, content_width: int, max_allowed_width: int):
        # Fallback if JS fails or goes wild
        if not content_width or content_width <= 0 or content_width > max_allowed_width * 3:
            content_width = max_allowed_width

        padding = 40  # small fudge for borders/padding/rounding
        proposed = max(100, min(content_width + padding, max_allowed_width))

        # Only allow shrinking if the viewport actually got smaller
        if self._last_width is not None and proposed < self._last_width:
            if max_allowed_width < self._last_width - 1:
                proposed = min(self._last_width, max_allowed_width)
            else:
                if (self._last_width - proposed) <= 4:
                    proposed = self._last_width
                else:
                    proposed = self._last_width

        if self._last_width is None or abs(self._last_width - proposed) > 1:
            self.setFixedWidth(proposed)
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
            self._last_width = proposed

            # Recompute height only if width actually changed
            QTimer.singleShot(0, self._viewer._adjust_height)

        QTimer.singleShot(0, lambda: setattr(self, "_sizing", False))


class UserChatBubbleWidget(_BubbleWidget):
    def __init__(self, text: str):
        super().__init__(text, is_user=True, bg_color="#282833", alias_attr="user_message")


class AssistantChatBubbleWidget(_BubbleWidget):
    def __init__(self, text: str):
        super().__init__(text, is_user=False, bg_color="#283328", alias_attr="llm_text")