import tomllib
from utility import getResourcePath
from os.path import join
class Settings:
    def __init__(self, settings_file='settings_default.toml'):
        self.settings_file = settings_file
        self.load()
        self.fill_default_sound_files()

    def set(self, key, value):
        self._settings[key] = value

    def get(self, *keys):
        assert 0 < len(keys) <= 2, f'Invalid number of keys: {len(keys)}'
        result = self._settings
        for key in keys:
            result = result.get(key, None)
        return result

    def load(self, settings_file=None):
        self._settings = {}
        if settings_file is None:
            settings_file = self.settings_file
        with open(settings_file, 'rb') as f:
            self._settings = tomllib.load(f)

    def fill_default_sound_files(self):
        default_sound_files = {
            'jump_plotted_sound_file': getResourcePath(join('sounds', 'carrier-jump-plotted.mp3')),
            'jump_completed_sound_file': getResourcePath(join('sounds', 'carrier-jump-completed.mp3')),
            'jump_cancelled_sound_file': getResourcePath(join('sounds', 'carrier-jump-cancelled.mp3')),
            'cooldown_finished_sound_file': getResourcePath(join('sounds', 'carrier-cooldown-finished.mp3')),
        }
        for key, value in default_sound_files.items():
            if  self.get('notifications')[key] == '':
                self._settings['notifications'][key] = value

if __name__ == '__main__':
    settings = Settings()
    print(settings._settings)
    print(settings.get('post_format', 'trade_post_string'))
    print(settings.get('post_format', 'wine_unload_string'))
