import tomllib
import json
from utility import getConfigSettingsDefaultPath, getResourcePath, getSettingsDefaultPath
from utility import getConfigSettingsPath
from os.path import join, exists
from shutil import copy2
import re

class SettingsValidationError(Exception):
    pass

class Settings:
    def __init__(self, settings_file=getSettingsDefaultPath()):
        self.settings_file = settings_file
        self.validation_errors = []
        self.validation_warnings = []

        # 1) Load the normal user-editable settings
        self.load()

        # 2) Validate & fill defaults
        self.validate()
        self.fill_default_sound_files()

        # 3) Load the config overrides and merge them in
        self.load_config()
        self.merge_config()

    def set(self, key, value):
        self._settings[key] = value

    def get(self, *keys):
        assert 0 < len(keys) <= 2, f'Invalid number of keys: {len(keys)}'
        result = self._settings
        for key in keys:
            if result is None:
                break
            result = result.get(key, None)
        if result is None:
            # check if key exists in default settings, if so, persist it into user config
            try:
                with open(getConfigSettingsDefaultPath(), 'r') as f:
                    default_cfg = json.load(f)
                default_val = default_cfg
                for key in keys:
                    default_val = default_val.get(key, None)
                    if default_val is None:
                        break
                if default_val is not None:
                    # persist this default into the user config
                    self.set_config(*keys, value=default_val)
                    # merge it back into in-memory settings
                    self.merge_config()
                    return default_val
            except Exception:
                pass
            return None
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
            if self.get('notifications', key) == '':
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
                    self.validation_warnings.append(f"Missing key: {full}, using default value")
                    curr[key] = dval
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
        if webhook and not re.match(r'^https://discord(?:app)?.com/api/webhooks/', webhook):
            self.validation_errors.append(f"discord.webhook does not look like a valid webhook URL: {webhook}")

        # 3) Check format for squadron_abbv
        abbv_list = self.get('name_customization', 'squadron_abbv')
        if abbv_list:
            if not all(len(item) == 1 and isinstance(item, dict) and
                isinstance(list(item.keys())[0], str) and isinstance(list(item.values())[0], str) and list(item.values())[0].isalnum()
                for item in abbv_list):
                self.validation_errors.append(f"Invalid format for squadron_abbv:\n {abbv_list}")

        # 4) Check plot reminder settings
        remind_seconds = self.get('plot_reminders', 'remind_seconds')
        warn_seconds = self.get('plot_reminders', 'warn_seconds')
        clear_seconds = self.get('plot_reminders', 'clear_seconds')
        if not remind_seconds > 0:
            self.validation_errors.append(f"plot_reminders.remind_seconds must be a positive integer, got: {remind_seconds}")
        if not remind_seconds > warn_seconds:
            self.validation_errors.append(f"plot_reminders.remind_seconds must be greater than warn_seconds, got: remind_seconds={remind_seconds}, warn_seconds={warn_seconds}")
        if not warn_seconds >= 0:
            self.validation_errors.append(f"plot_reminders.warn_seconds must be a non-negative integer, got: {warn_seconds}")
        if not clear_seconds >= 0:
            self.validation_errors.append(f"plot_reminders.clear_seconds must be a non-negative integer, got: {clear_seconds}")
        
        if self.validation_errors:
            raise SettingsValidationError("Settings validation failed:\n" + "\n".join(self.validation_errors))
        # if self.validation_warnings:
        #     print("Warnings:\n" + "\n".join(self.validation_warnings))
        # print("Settings validation passed")

    def load_config(self, prog_file=None):
        """Load UI-driven overrides (if present)."""
        if prog_file is None:
            prog_file = getConfigSettingsPath()
        try:
            if not exists(prog_file):
                copy2(getConfigSettingsDefaultPath(), prog_file)
                print(f"Created config file: {prog_file}")
                with open(prog_file, 'r') as f:
                    self._config = json.load(f)
                self.save_config(prog_file)
            else:
                with open(prog_file, 'r') as f:
                    self._config = json.load(f)
        except json.JSONDecodeError:
            with open(getConfigSettingsDefaultPath(), 'r') as f:
                self._config = json.load(f)
            self.validation_warnings.append(f"Could not parse config settings file {prog_file}, using defaults\n {prog_file} has been reset\n You should not edit this file manually!")

    def merge_config(self):
        """Deep-merge config settings on top of the loaded user settings."""
        def _merge(src, dest):
            for k, v in src.items():
                if isinstance(v, dict) and isinstance(dest.get(k), dict):
                    _merge(v, dest[k])
                else:
                    dest[k] = v
        _merge(self._config, self._settings)

    def set_config(self, *keys, value):
        """
        Update a config setting (nested via multiple keys) and persist it.
        Example: set_config('notifications', 'cooldown', value='/…')
        """
        d = self._config
        for k in keys[:-1]:
            d = d.setdefault(k, {})
        d[keys[-1]] = value
        self.save_config()

    def save_config(self, prog_file=None):
        """Write out the config overrides json so they persist."""
        if prog_file is None:
            prog_file = getConfigSettingsPath()
        with open(prog_file, 'w') as f:
            json.dump(self._config, f)

if __name__ == '__main__':
    from utility import getSettingsPath
    settings = Settings(getSettingsPath())
    print(*settings._settings.items(), sep='\n')
    print(f'{"\n".join(settings.validation_warnings)}') if settings.validation_warnings else print('No warnings')
    # print(settings.get('post_format'))
    # print(settings.get('post_format', 'trade_post_string'))
