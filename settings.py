import tomllib
class Settings:
    def __init__(self, settings_file='settings_default.toml'):
        self.settings_file = settings_file
        self.load()

    def set(self, key, value):
        self._settings[key] = value

    def get(self, key):
        return self._settings.get(key, None)
    
    def load(self, settings_file=None):
        self._settings = {}
        if settings_file is None:
            settings_file = self.settings_file
        with open(settings_file, 'rb') as f:
            self._settings = tomllib.load(f)

if __name__ == '__main__':
    settings = Settings()
    settings.load()
    print(settings._settings)
    print(settings.get('post_format')['trade_post_string'])
    print(settings.get('post_format')['wine_unload_string'])
    