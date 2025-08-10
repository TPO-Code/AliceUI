import json


class _ApplicationData:
    """
    A singleton class to manage application data, allowing access
    to nested dictionary values using dot notation strings.

    Example:
        app_data.set("settings.theme.color", "blue")
        color = app_data.get("settings.theme.color")
    """
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(_ApplicationData, cls).__new__(cls, *args, **kwargs)
            # Initialize the internal data store
            cls._instance._appdata = {
                "Settings": {},
                "messages": [],
            }
        return cls._instance

    def save_application_data(self, filename="appdata.json"):
        """Saves the current application data to a JSON file."""
        try:
            with open(filename, 'w') as f:
                json.dump(self._appdata, f, indent=4)
            print(f"Application data saved to {filename}")
        except IOError as e:
            print(f"Error saving application data: {e}")

    def load_application_data(self, filename="appdata.json"):
        """Loads application data from a JSON file."""
        try:
            with open(filename, 'r') as f:
                self._appdata = json.load(f)
            print(f"Application data loaded from {filename}")
        except FileNotFoundError:
            print(f"No save file found at {filename}. Starting with default data.")
        except json.JSONDecodeError:
            print(f"Error decoding JSON from {filename}. Starting with default data.")
        except IOError as e:
            print(f"Error loading application data: {e}")

    # --- NEW METHODS ---

    def get(self, key_path, default=None):
        """
        Retrieves a value from the nested data using a dot-separated path.

        Args:
            key_path (str): The dot-separated path (e.g., "settings.ollama.url").
            default: The value to return if the key_path is not found.

        Returns:
            The requested value or the default.
        """
        keys = key_path.split('.')

        current_level = self._appdata
        try:
            for key in keys:
                current_level = current_level[key]
            return current_level
        except (KeyError, TypeError):
            self.set(key_path,default)
            return default

    def set(self, key_path, value):
        """
        Sets a value in the nested data using a dot-separated path.
        Creates nested dictionaries as needed.

        Args:
            key_path (str): The dot-separated path (e.g., "settings.colors.background").
            value: The value to set at the specified path.
        """
        keys = key_path.split('.')
        # Make the first key case-insensitive
        if keys and keys[0].lower() in ['settings', 'conversation']:
            keys[0] = keys[0].title()

        current_level = self._appdata

        # Traverse or create dictionaries until the last key
        for key in keys[:-1]:
            # setdefault is perfect here: it gets the key's value, but if the
            # key doesn't exist, it sets it to {} and returns that new dict.
            current_level = current_level.setdefault(key, {})
            if not isinstance(current_level, dict):
                raise TypeError(f"Cannot set value: part of the path '{key}' is not a dictionary.")

        # Set the final value
        current_level[keys[-1]] = value



app_data=_ApplicationData()
app_data.load_application_data()
#app_data.save_application_data()



