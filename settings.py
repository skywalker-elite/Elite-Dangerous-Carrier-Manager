import tomllib
from utility import getResourcePath, getSettingsDefaultPath
from os.path import join, exists
import re

class SettingsValidationError(Exception):
    pass

class Settings:
    def __init__(self, settings_file=getSettingsDefaultPath()):
        self.settings_file = settings_file
        self.validation_errors = []
        self.validation_warnings = []
        self.load()
        self.validate()
        self.fill_default_sound_files()

    def set(self, key, value):
        self._settings[key] = value

    def get(self, *keys):
        assert 0 < len(keys) <= 2, f'Invalid number of keys: {len(keys)}'
        result = self._settings
        for key in keys:
            if result is None:
                return None
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
            if  self.get('notifications', key) == '':
                self._settings['notifications'][key] = value

    def validate(self):
        """Raise ValueError if user settings diverge from default structure or types."""
        # load defaults
        with open(getSettingsDefaultPath(), 'rb') as f:
            defaults = tomllib.load(f)

        self.validation_errors = []
        self.validation_warnings = []

        def _compare(dflt, curr, path=''):
            # Check all default keys
            for key, dval in dflt.items():
                full = f"{path}{key}"
                if key not in curr:
                    self.validation_errors.append(f"Missing key: {full}")
                    continue

                cval = curr[key]
                # nested section
                if isinstance(dval, dict):
                    if not isinstance(cval, dict):
                        self.validation_errors.append(f"Type mismatch at {full}: expected section")
                    else:
                        _compare(dval, cval, full + '.')
                else:
                    if not isinstance(cval, type(dval)):
                        self.validation_errors.append(
                            f"Type mismatch at {full}: "
                            f"expected {type(dval).__name__}, got {type(cval).__name__}"
                        )

            # Check for any extra keys
            for key in curr:
                if key not in dflt:
                    self.validation_warnings.append(f"Unknown key: {path}{key}")

        _compare(defaults, self._settings)

        # Additional checks
        # 1) If user set a custom sound_file, verify it exists
        for sec in ('notifications',):
            for sfx in ('jump_plotted_sound_file',
                        'jump_completed_sound_file',
                        'jump_cancelled_sound_file',
                        'cooldown_finished_sound_file'):
                val = self.get(sec, sfx)
                if val and not exists(val):
                    self.validation_errors.append(f"Sound file not found: {sec}.{sfx} -> {val}")

        # 2) Simple webhook URL check
        webhook = self.get('discord', 'webhook') or ''
        if webhook and not re.match(r'^https://discord.com/api/webhooks/', webhook):
            self.validation_errors.append(f"discord.webhook does not look like a valid webhook URL: {webhook}")

        if self.validation_errors:
            raise SettingsValidationError("Settings validation failed:\n" + "\n".join(self.validation_errors))
        # if self.validation_warnings:
        #     print("Warnings:\n" + "\n".join(self.validation_warnings))
        # print("Settings validation passed")

if __name__ == '__main__':
    from utility import getSettingsPath
    settings = Settings(getSettingsPath())
    print(settings._settings)
    # print(settings.get('post_format'))
    # print(settings.get('post_format', 'trade_post_string'))
