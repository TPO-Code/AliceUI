# debug_logger.py
import inspect
import os
import logging
import sys
import atexit
from queue import Queue
from logging.handlers import QueueHandler, QueueListener, TimedRotatingFileHandler

import platformdirs
#from application_details import application_paths
APP_NAME = "Tpo-Tutor"
APP_AUTHOR = "Two Pint Ohh"
# --- Define custom log levels ---
VERBOSE_LEVEL_NUM = 5
VERBOSE_LEVEL_NAME = "VERBOSE"
logging.addLevelName(VERBOSE_LEVEL_NAME, VERBOSE_LEVEL_NUM)

FATAL_LEVEL_NUM = 60
FATAL_LEVEL_NAME = "FATAL"
logging.addLevelName(FATAL_LEVEL_NAME, FATAL_LEVEL_NUM)


# -------------------- NEW: THE CLASS-BASED APPROACH --------------------
class CustomLogger(logging.Logger):
    """
    A custom logger class that adds support for 'verbose' and 'fatal' levels.
    """

    def verbose(self, message, *args, **kws):
        """Logs a message with level VERBOSE."""
        if self.isEnabledFor(VERBOSE_LEVEL_NUM):
            self._log(VERBOSE_LEVEL_NUM, message, args, **kws)

    def fatal(self, message, *args, **kws):
        """Logs a message with level FATAL."""
        if self.isEnabledFor(FATAL_LEVEL_NUM):
            self._log(FATAL_LEVEL_NUM, message, args, **kws)


# --- CRUCIAL: Tell the logging module to use our class for all new loggers ---
# This must be done BEFORE any loggers are instantiated.
logging.setLoggerClass(CustomLogger)
# -------------------------------------------------------------------------


LOG_LEVEL_MAP = {
    'VERBOSE': VERBOSE_LEVEL_NUM,
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARNING': logging.WARNING,
    'ERROR': logging.ERROR,
    'CRITICAL': logging.CRITICAL,
    'FATAL': FATAL_LEVEL_NUM,
}
log_level_str = "DEBUG"
APP_LOG_LEVEL = LOG_LEVEL_MAP.get(log_level_str, logging.INFO)

# 3. Define the full path to your log file
log_file_path = "./log.log" #application_paths.log_file
(os.getcwd(), "logs", "app.log")

_IS_CONFIGURED = False
_listener = None


class CustomFormatter(logging.Formatter):
    """Custom formatter with colors for the entire message body."""
    GREY = "\x1b[38;2m"
    CYAN = "\x1b[36m"
    GREEN = "\x1b[32m"
    YELLOW = "\x1b[33m"
    RED = "\x1b[31m"
    BOLD_RED = "\x1b[31;1m"
    BRIGHT_MAGENTA = "\x1b[35;1m"
    RESET = "\x1b[0m"

    log_format = "%(asctime)s - %(levelname)-8s - [%(name)s] - %(message)s"

    FORMATS = {
        VERBOSE_LEVEL_NUM: CYAN,
        logging.DEBUG: GREY,
        logging.INFO: GREEN,
        logging.WARNING: YELLOW,
        logging.ERROR: RED,
        logging.CRITICAL: BOLD_RED,
        FATAL_LEVEL_NUM: BRIGHT_MAGENTA,
    }

    def __init__(self):
        super().__init__(self.log_format, datefmt="%Y-%m-%d %H:%M:%S")

    def format(self, record):
        log_message = super().format(record)
        timestamp, separator, message_body = log_message.partition(' - ')
        log_color = self.FORMATS.get(record.levelno)
        colored_message = f"{timestamp}{separator}{log_color}{message_body}{self.RESET}"
        return colored_message


def _shutdown_handler():
    """Gracefully stop the listener on program exit."""
    global _listener
    if _listener:
        # Get a logger instance to log the shutdown message
        shutdown_logger = get_logger("logger.shutdown")
        shutdown_logger.info("Shutting down logger and flushing queue...")
        _listener.stop()


def setup_logger(level: int = logging.INFO, log_file: str = "app.log"):
    """Sets up a decoupled, asynchronous logger for the application."""
    global _IS_CONFIGURED, _listener
    if _IS_CONFIGURED:
        return

    # Handlers will inherit the level from the main logger
    handlers = []
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(CustomFormatter())
    handlers.append(console_handler)

    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        file_formatter = logging.Formatter(
            "%(asctime)s - %(levelname)-8s - [%(name)s] - %(message)s (%(filename)s:%(lineno)d)",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler = TimedRotatingFileHandler(
            log_file, when='D', interval=1, backupCount=7, utc=True
        )
        file_handler.setFormatter(file_formatter)
        handlers.append(file_handler)

    log_queue = Queue(-1)
    _listener = QueueListener(log_queue, *handlers, respect_handler_level=False)
    _listener.start()

    # Get our dedicated application logger. It will be an instance of CustomLogger now.
    app_logger: CustomLogger = logging.getLogger(APP_NAME)
    app_logger.setLevel(level)

    # Clear existing handlers to avoid duplicates on re-configuration scenarios
    if app_logger.hasHandlers():
        app_logger.handlers.clear()

    queue_handler = QueueHandler(log_queue)
    app_logger.addHandler(queue_handler)
    app_logger.propagate = False

    atexit.register(_shutdown_handler)
    _IS_CONFIGURED = True
    get_logger("logger.setup").info("Decoupled asynchronous logger configured successfully.")


# --- MODIFIED: Helper function now correctly typed ---
def _get_namespaced_logger(prefix: str) -> CustomLogger:
    """Helper to create a logger name within our app's namespace."""
    # Since we called setLoggerClass, this will return a CustomLogger instance.
    return logging.getLogger(f"{APP_NAME}.{prefix}")


# --- Helper functions are now namespaced ---
def _get_namespaced_logger(prefix: str) -> logging.Logger:
    """Helper to create a logger name within our app's namespace."""
    return logging.getLogger(f"{APP_NAME}.{prefix}")


def verbose(prefix: str, message: str):
    _get_namespaced_logger(prefix).verbose(message, stacklevel=2)


def debug(prefix: str, message: str):
    _get_namespaced_logger(prefix).debug(message, stacklevel=2)


def info(prefix: str, message: str):
    _get_namespaced_logger(prefix).info(message, stacklevel=2)


def warning(prefix: str, message: str):
    _get_namespaced_logger(prefix).warning(message, stacklevel=2)


def error(prefix: str, message: str, exc_info: bool = False):
    _get_namespaced_logger(prefix).error(message, exc_info=exc_info, stacklevel=2)


def critical(prefix: str, message: str, exc_info: bool = False):
    _get_namespaced_logger(prefix).critical(message, exc_info=exc_info, stacklevel=2)


def fatal(prefix: str, message: str, exc_info: bool = False):
    _get_namespaced_logger(prefix).fatal(message, exc_info=exc_info, stacklevel=2)


def get_logger(prefix=None) -> logging.Logger:
    """
    Returns a logger instance with a name automatically determined by the
    calling context.

    - If called from a class method, the name is the class name.
    - If called from a function, the name is the function name.
    - If called from the module level, the name is the module's name.
    """
    # We want the frame of the caller, which is 1 level up in the stack.
    # inspect.stack()[0] is the current frame (get_logger)
    # inspect.stack()[1] is the caller's frame
    if prefix:
        return _get_namespaced_logger(prefix)
    frame = None
    try:
        frame = inspect.stack()[1].frame

        # Check if the caller is a method of a class
        # 'self' is the conventional name for an instance in a method's local scope
        if 'self' in frame.f_locals:
            # It's an instance method, get the class name from the instance
            class_name = frame.f_locals['self'].__class__.__name__
            return _get_namespaced_logger(class_name)

        # 'cls' is the conventional name for a class in a classmethod's local scope
        if 'cls' in frame.f_locals:
            # It's a class method, get the class name from the class object
            class_name = frame.f_locals['cls'].__name__
            return _get_namespaced_logger(class_name)

        # If not in a class, use the function name
        func_name = frame.f_code.co_name
        # If called from the top level of a module, the name is '<module>'
        if func_name == '<module>':
            # Fall back to the module name, which is more useful
            module_name = frame.f_globals['__name__']
            return _get_namespaced_logger(module_name)

        return _get_namespaced_logger(func_name)

    finally:
        # According to the docs, it's important to delete the frame
        # to avoid reference cycles.
        del frame


# Initialize the logger on import
setup_logger(level=APP_LOG_LEVEL, log_file=log_file_path)