import tomllib
class Settings:
    def __init__(self, settings_file='settings_default.toml'):
        self.settings_file = settings_file
        self._settings = {
            # 'trade_post_string': '/cco $trade_type carrier:$carrier_name commodity:$commodity system:$system station:$station profit:$profit pads:$pad_size $demand_supply: $amount',
            # 'wine_unload_string': '/wine_unload carrier_id: $callsign planetary_body: $body',
        }
        self.load()

    def set(self, key, value):
        self._settings[key] = value

    def get(self, key):
        return self._settings.get(key, None)
    
    def load(self):
        with open(self.settings_file, 'rb') as f:
            self._settings = tomllib.load(f)

if __name__ == '__main__':
    settings = Settings()
    settings.load()
    print(settings._settings)
    print(settings.get('post_format')['trade_post_string'])
    print(settings.get('post_format')['wine_unload_string'])
    