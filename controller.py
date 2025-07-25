import threading
import time
import pyperclip
import re
from webbrowser import open_new_tab
# from winotify import Notification TODO: for notification without popup
from datetime import datetime, timezone, timedelta, date
from os import makedirs, path
from shutil import copyfile
import traceback
import tomllib
from string import Template
from playsound3 import playsound
from settings import Settings, SettingsValidationError
from model import CarrierModel
from view import CarrierView, TradePostView, ManualTimerView
from station_parser import EDSMError, getStations
from utility import checkTimerFormat, getCurrentVersion, getLatestVersion, isUpdateAvailable, getSettingsPath, getSettingsDefaultPath, getSettingsDir
from discord_handler import DiscordWebhookHandler
from config import PLOT_WARN, UPDATE_INTERVAL, REDRAW_INTERVAL_FAST, REDRAW_INTERVAL_SLOW, REMIND_INTERVAL, PLOT_REMIND, ladder_systems

class CarrierController:
    def __init__(self, root, model:CarrierModel):
        self.model = model
        self.view = CarrierView(root)
        self.model.register_status_change_callback(self.status_change)
        self.load_settings(getSettingsPath())
        self.view.button_get_hammer.configure(command=self.button_click_hammer)
        self.view.button_post_trade.configure(command=self.button_click_post_trade)
        self.view.button_manual_timer.configure(command=self.button_click_manual_timer)
        self.view.button_clear_timer.configure(command=self.button_click_clear_timer)
        self.view.button_post_departure.configure(command=self.button_click_post_departure)
        self.view.button_post_trade_trade.configure(command=self.button_click_post_trade_trade)
        self.view.button_check_updates.configure(command=lambda: self.check_app_update(notify_is_latest=True))
        self.view.button_reload_settings.configure(command=self.button_click_reload_settings)
        self.view.button_open_settings.configure(command=lambda: open_new_tab(url=getSettingsPath()))
        self.view.button_reset_settings.configure(command=self.button_click_reset_settings)
        self.view.button_open_settings_dir.configure(command=lambda: open_new_tab(url=getSettingsDir()))
        self.view.button_test_trade_post.configure(command=self.button_click_test_trade_post)
        self.view.button_test_wine_unload.configure(command=self.button_click_test_wine_unload)
        self.view.button_test_discord.configure(command=self.button_click_test_discord_webhook)
        self.view.button_test_discord_ping.configure(command=self.button_click_test_discord_webhook_ping)

        # Start the carrier update loop
        self.update_journals()

        # Start the UI update loop
        self.redraw_fast()
        self.redraw_slow()

        self.set_current_version()
        self.check_app_update()

    def set_current_version(self):
        self.view.label_version.configure(text=getCurrentVersion())
    
    def check_app_update(self, notify_is_latest:bool=False):
        if isUpdateAvailable():
            if self.view.show_message_box_askyesno('Update Available', f'New version available: {getLatestVersion()}\n Go to download?'):
                open_new_tab(url='https://github.com/skywalker-elite/Elite-Dangerous-Carrier-Manager/releases/latest')
        elif notify_is_latest:
            self.view.show_message_box_info('No update available', f'You are using the latest version: {getCurrentVersion()}')
    
    def load_settings(self, settings_file:str):
        try:
            self.settings = Settings(settings_file=settings_file)
        except FileNotFoundError as e:
            if settings_file == getSettingsDefaultPath():
                raise e
            else:
                if self.view.show_message_box_askyesno('Settings file not found', 'Do you want to create a new settings file?'):
                    makedirs(getSettingsDir(), exist_ok=True)
                    copyfile(getSettingsDefaultPath(), settings_file)
                    if self.view.show_message_box_askyesno('Success!', 'Settings file created using default settings. \nDo you want to edit it now?'):
                        open_new_tab(url=settings_file)
                        self.view.show_message_box_info_no_topmost('Waiting', 'Click OK when you are done editing and saved the file')
                    self.settings = Settings(settings_file=settings_file)
                else:
                    self.view.show_message_box_info('Settings', 'Using default settings')
                    self.settings = Settings(settings_file=getSettingsDefaultPath())
        except tomllib.TOMLDecodeError as e:
            if settings_file == getSettingsDefaultPath():
                raise e
            else:
                self.view.show_message_box_warning('Settings file corrupted', f'Using default settings\n{e}')
                self.settings = Settings(settings_file=getSettingsDefaultPath())
        except SettingsValidationError as e:
            if settings_file == getSettingsDefaultPath():
                raise e
            else:
                self.view.show_message_box_warning('Settings file validation failed', f'{e}\nUsing default settings')
                self.settings = Settings(settings_file=getSettingsDefaultPath())
        finally:
            if self.settings.validation_warnings:
                self.view.show_message_box_warning('Settings file warnings', f'{"\n".join(self.settings.validation_warnings)}')
            self.webhook_handler = DiscordWebhookHandler(self.settings.get('discord', 'webhook'), self.settings.get('discord', 'userID'))
            self.model.reset_ignore_list()
            self.model.add_ignore_list(self.settings.get('advanced', 'ignore_list'))
            self.model.custom_order = self.settings.get('advanced', 'custom_order')
            self.view.set_font_size(self.settings.get('font_size', 'UI'), self.settings.get('font_size', 'table'))

    def status_change(self, carrierID:str, status_old:str, status_new:str):
        # print(f'{self.model.get_name(carrierID)} ({self.model.get_callsign(carrierID)}) status changed from {status_old} to {status_new}')
        if status_new == 'jumping':
            # jump plotted
            # print(f'{self.model.get_name(carrierID)} ({self.model.get_callsign(carrierID)}) plotted jump to {self.model.get_destination_system(carrierID)} body {self.model.get_destination_body(carrierID)}')
            if self.settings.get('notifications', 'jump_plotted'):
                self.view.show_message_box_info('Jump plotted', f'{self.model.get_name(carrierID)} ({self.model.get_callsign(carrierID)}) plotted jump to {self.model.get_destination_system(carrierID, use_custom_name=True)} body {self.model.get_destination_body(carrierID)}')
            if self.settings.get('notifications', 'jump_plotted_sound'):
                self.play_sound(self.settings.get('notifications', 'jump_plotted_sound_file'))
            if self.settings.get('notifications', 'jump_plotted_discord'):
                title = f'{self.model.get_name(carrierID)} ({self.model.get_callsign(carrierID)})'
                description = f'Jump plotted to **{self.model.get_destination_system(carrierID, use_custom_name=True)}** body **{self.model.get_destination_body(carrierID)}**, arriving {self.model.get_departure_hammer_countdown(carrierID)}'
                self.webhook_handler.send_message_with_embed(title=title, description=description, ping=self.settings.get('notifications', 'jump_plotted_discord_ping'))
        elif status_new == 'cool_down':
            # jump completed
            # print(f'{self.model.get_name(carrierID)} ({self.model.get_callsign(carrierID)}) has arrived at {self.model.get_current_system(carrierID)} body {self.model.get_current_body(carrierID)}')
            if self.settings.get('notifications', 'jump_completed'):
                self.view.show_message_box_info('Jump completed', f'{self.model.get_name(carrierID)} ({self.model.get_callsign(carrierID)}) has arrived at {self.model.get_current_system(carrierID, use_custom_name=True)} body {self.model.get_current_body(carrierID)}')
            if self.settings.get('notifications', 'jump_completed_sound'):
                self.play_sound(self.settings.get('notifications', 'jump_completed_sound_file'))
            if self.settings.get('notifications', 'jump_completed_discord'):
                title = f'{self.model.get_name(carrierID)} ({self.model.get_callsign(carrierID)})'
                description = f'Jump completed at **{self.model.get_current_system(carrierID, use_custom_name=True)}** body **{self.model.get_current_body(carrierID)}**'
                self.webhook_handler.send_message_with_embed(title=title, description=description, ping=self.settings.get('notifications', 'jump_completed_discord_ping'))
        elif status_new == 'cool_down_cancel':
            # jump cancelled
            # print(f'{self.model.get_name(carrierID)} ({self.model.get_callsign(carrierID)}) cancelled a jump')
            if self.settings.get('notifications', 'jump_cancelled'):
                self.view.show_message_box_info('Jump cancelled', f'{self.model.get_name(carrierID)} ({self.model.get_callsign(carrierID)}) cancelled a jump')
            if self.settings.get('notifications', 'jump_cancelled_sound'):
                self.play_sound(self.settings.get('notifications', 'jump_cancelled_sound_file'))
            if self.settings.get('notifications', 'jump_cancelled_discord'):
                title = f'{self.model.get_name(carrierID)} ({self.model.get_callsign(carrierID)})'
                description = f'Jump cancelled'
                self.webhook_handler.send_message_with_embed(title=title, description=description, ping=self.settings.get('notifications', 'jump_cancelled_discord_ping'))
        elif status_new == 'idle' and status_old in ['cool_down', 'cool_down_cancel']:
            # cool down complete
            # print(f'{self.model.get_name(carrierID)} ({self.model.get_callsign(carrierID)}) has finished cool down and is ready to jump')
            if self.settings.get('notifications', 'cooldown_finished'):
                self.view.show_message_box_info('Cool down complete', f'{self.model.get_name(carrierID)} ({self.model.get_callsign(carrierID)}) has finished cool down and is ready to jump')
            if self.settings.get('notifications', 'cooldown_finished_sound'):
                self.play_sound(self.settings.get('notifications', 'cooldown_finished_sound_file'))
            if self.settings.get('notifications', 'cooldown_finished_discord'):
                title = f'{self.model.get_name(carrierID)} ({self.model.get_callsign(carrierID)})'
                description = f'Cool down complete, ready to jump'
                self.webhook_handler.send_message_with_embed(title=title, description=description, ping=self.settings.get('notifications', 'cooldown_finished_discord_ping'))

    def play_sound(self, sound_file:str, block:bool=False):
        if path.exists(sound_file):
            self.sound = playsound(sound_file, block=block)
        else:
            self.view.show_message_box_warning('Error', f'Sound file {sound_file} not found')

    def button_click_reload_settings(self):
        try:
            self.load_settings(getSettingsPath())
            self.view.show_message_box_info('Success!', 'Settings reloaded')
        except Exception as e:
            self.view.show_message_box_warning('Error', f'Error while reloading settings\n{traceback.format_exc()}')
    
    def button_click_reset_settings(self):
        if self.view.show_message_box_askyesno('Reset settings', 'Do you want to reset the settings to default?'):
            try:
                copyfile(getSettingsDefaultPath(), getSettingsPath())
                self.load_settings(getSettingsPath())
                self.view.show_message_box_info('Success!', 'Settings reset to default')
            except Exception as e:
                self.view.show_message_box_warning('Error', f'Error while resetting settings\n{traceback.format_exc()}')
    
    def update_tables_fast(self, now):
        self.model.update_carriers(now)
        self.view.update_table_jumps(self.model.get_data(now), self.model.get_rows_pending_decom())
    
    def update_tables_slow(self, now):
        pending_decom = self.model.get_rows_pending_decom()
        self.view.update_table_finance(self.model.get_data_finance(), pending_decom)
        self.view.update_table_trade(*self.model.get_data_trade())
        self.view.update_table_services(self.model.get_data_services(), pending_decom) #TODO: reduce update rate for performance
        self.view.update_table_misc(self.model.get_data_misc(), pending_decom) #TODO: reduce update rate for performance

    def update_time(self, now):
        self.view.update_time(now.strftime('%H:%M:%S'))
    
    def update_journals(self):
        try:
            self.model.read_journals()  # Re-read journals and update model's data
        except Exception as e:
            if self.view.show_message_box_askretrycancel('Error', f'An error occurred during journal update\n{traceback.format_exc()}'):
                self.view.root.after(UPDATE_INTERVAL, self.update_journals)
            else:
                self.view.root.destroy()
        else:
            self.view.root.after(UPDATE_INTERVAL, self.update_journals)
    
    def button_click_hammer(self):
        selected_row = self.get_selected_row()
        if selected_row is not None:
            carrierID = self.model.sorted_ids_display()[selected_row]
            carrier_name = self.model.get_name(carrierID)
            carrier_callsign = self.model.get_callsign(carrierID)
            hammer_countdown = self.model.get_departure_hammer_countdown(carrierID)
            if hammer_countdown is not None:
                self.copy_to_clipboard(hammer_countdown, 'Success!', f'Hammertime countdown for {carrier_name} ({carrier_callsign}) copied!')
            else:
                self.view.show_message_box_warning('Error', f'No jump data found for {carrier_name} ({carrier_callsign})')
        else:
            self.view.show_message_box_warning('Warning', 'please select one carrier and one carrier only!')

    def button_click_post_trade(self):
        selected_row = self.get_selected_row()
        self.handle_post_trade_logic(selected_row, self.model.sorted_ids_display(), self.view.sheet_jumps)

    def button_click_post_trade_trade(self):
        selected_row = self.get_selected_row(sheet=self.view.sheet_trade)
        self.handle_post_trade_logic(selected_row, self.model.trade_carrierIDs, self.view.sheet_trade)

    def handle_post_trade_logic(self, selected_row, carrier_ids, sheet):
        if selected_row is not None:
            carrierID = carrier_ids[selected_row]
            carrier_name = self.model.get_name(carrierID)
            system = self.model.get_current_or_destination_system(carrierID)
            carrier_callsign = self.model.get_callsign(carrierID)
            if sheet.name == 'sheet_trade':
                trade_type, amount, commodity, price = self.view.sheet_trade.data[selected_row][1:5]
                trade_type = trade_type.lower()
                amount = float(amount.replace(',',''))
                amount = round(amount / 500) * 500 / 1000
                if amount % 1 == 0:
                    amount = int(amount)
                order = (trade_type, commodity, amount, price)
            elif sheet.name == 'sheet_jumps':
                order = self.model.get_formated_largest_order(carrierID=carrierID)
            else:
                raise RuntimeError(f'Unexpected sheet name: {sheet.name}')

            if system == 'HIP 58832':
                if order is not None:
                    trade_type, commodity, amount, price = order
                    if trade_type == 'unloading' and commodity == 'Wine':
                        body_id = self.model.get_current_or_destination_body_id(carrierID=carrierID)
                        planetary_body = {0: 'Star', 1: 'Planet 1', 2: 'Planet 2', 3: 'Planet 3', 4: 'Planet 4', 5: 'Planet 5', 16: 'Planet 6'}.get(body_id, None) # Yes, the body_id of Planet 6 is 16, don't ask me why
                        if planetary_body is not None:
                            # post_string = f'/wine_unload carrier_id: {carrier_callsign} planetary_body: {body}'
                            post_string = self.generate_wine_unload_post_string(carrier_callsign=carrier_callsign, planetary_body=planetary_body)
                            try:
                                pyperclip.copy(post_string)
                            except pyperclip.PyperclipException as e:
                                self.view.show_message_box_warning('Error', f'Error while copying to clipboard\n{e}')
                            else:
                                self.view.show_message_box_info('Wine o\'clock', 'Wine unload command copied')
                        else:
                            self.view.show_message_box_warning('Error', f'Something went really wrong, please contact the developer and provide the following:\n {system=}, {body_id=}, {planetary_body=}')
                    else:
                        self.view.show_message_box_warning('What?', 'This carrier is at the peak, it can only unload wine, everything else is illegal')
                else:
                    self.view.show_message_box_warning('No trade order', f'There is no trade order set for {carrier_name} ({carrier_callsign})')
            else:
                if order is not None:
                    trade_type, commodity, amount, price = order
                    try:
                        stations, pad_sizes, market_ids, market_updated = getStations(sys_name=system)
                    except EDSMError as e:
                        self.view.show_message_box_warning('Error', f'Error fetching station data: {e}')
                        return
                    L = [i for i, ps in enumerate(pad_sizes) if ps == 'L']
                    M = [i for i, ps in enumerate(pad_sizes) if ps == 'M']
                    stations = [stations[i] for i in L + M]
                    pad_sizes = [pad_sizes[i] for i in L + M]
                    market_ids = [market_ids[i] for i in L + M]
                    market_updated = [market_updated[i] for i in L + M]
                    if len(stations) > 0:
                        self.trade_post_view = TradePostView(self.view.root, carrier_name=carrier_name, trade_type=trade_type, commodity=commodity, stations=stations, pad_sizes=pad_sizes, system=system, amount=amount, market_ids=market_ids, market_updated=market_updated, price=price)
                        self.trade_post_view.button_post.configure(command=lambda: self.button_click_post(carrier_name=carrier_name, carrier_callsign=carrier_callsign, trade_type=trade_type, commodity=commodity, system=system, amount=amount))
                    else:
                        self.view.show_message_box_warning('No station', f'There are no stations in this system ({system})')
                else:
                    self.view.show_message_box_warning('No trade order', f'There is no trade order set for {carrier_name} ({carrier_callsign})')
        else:
            self.view.show_message_box_warning('Warning', f'please select one {"carrier" if sheet.name == "sheet_jumps" else "trade"} and one {"carrier" if sheet.name == "sheet_jumps" else "trade"} only!')
    
    def button_click_post(self, carrier_name:str, carrier_callsign:str, trade_type:str, commodity:str, system:str, amount:int|float):
        # /cco load carrier:P.T.N. Rocinante commodity:Agronomic Treatment system:Leesti station:George Lucas profit:11 pads:L demand:24
        # s = '/cco {trade_type} carrier:{carrier_name} commodity:{commodity} system:{system} station:{station} profit:{profit} pads:{pad_size} {demand_supply}: {amount}'
        s = Template(self.settings.get('post_format', 'trade_post_string'))
        station = self.trade_post_view.cbox_stations.get()
        profit = self.trade_post_view.cbox_profit.get()
        pad_size = self.trade_post_view.cbox_pad_size.get()
        match pad_size:
            case 'L':
                pad_size = 'Large'
                pad_size_short = 'L'
            case 'M':
                pad_size = 'Medium'
                pad_size_short = 'M'
            case _:
                raise RuntimeError(f'Unexpected pad_size: {pad_size}')

        match trade_type:
            case 'loading':
                trade_type = 'load'
                trading_type = 'loading'
                demand_supply = 'demand'
                to_from = 'from'
            case 'unloading':
                trade_type = 'unload'
                trading_type = 'unloading'
                demand_supply = 'supply'
                to_from = 'to'
            case _:
                raise RuntimeError(f'Unexpected trade_type: {trade_type}')

        # post_string = s.format(trade_type=trade_type.replace('ing', ''), carrier_name=carrier_name, commodity=commodity, system=system, station=station, profit=profit, pad_size=pad_size, demand_supply='demand' if trade_type=='loading'else 'supply', amount=amount)
        post_string = self.generate_trade_post_string(
            trade_type=trade_type,
            trading_type=trading_type,
            carrier_name=carrier_name,
            carrier_callsign=carrier_callsign,
            commodity=commodity,
            system=system,
            station=station,
            profit=profit,
            pad_size=pad_size,
            pad_size_short=pad_size_short,
            demand_supply=demand_supply,
            amount=amount,
            to_from=to_from
        )
        self.copy_to_clipboard(post_string, None, None, on_success=lambda: self.trade_post_view.popup.destroy())

    def generate_trade_post_string(self, trade_type:str, trading_type:str, carrier_name:str, carrier_callsign:str, commodity:str, system:str, station:str, profit:str, pad_size:str, pad_size_short:str, demand_supply:str, amount:int|float, to_from:str) -> str:
        s = Template(self.settings.get('post_format', 'trade_post_string'))
        post_string = s.safe_substitute(
            trade_type=trade_type,
            trading_type=trading_type,
            carrier_name=carrier_name,
            carrier_callsign=carrier_callsign,
            commodity=commodity,
            system=system,
            station=station,
            profit=profit,
            pad_size=pad_size,
            pad_size_short=pad_size_short,
            demand_supply=demand_supply,
            amount=amount,
            to_from=to_from
        )
        return post_string

    def generate_wine_unload_post_string(self, carrier_callsign:str, planetary_body:str) -> str:
        s = Template(self.settings.get('post_format', 'wine_unload_string'))
        post_string = s.safe_substitute(carrier_callsign=carrier_callsign, planetary_body=planetary_body)
        return post_string
    
    def copy_to_clipboard(self, text, success_title, success_message, on_success=None):
        try:
            pyperclip.copy(text)
        except pyperclip.PyperclipException as e:
            self.view.show_message_box_warning('Error', f'Error while copying to clipboard\n{e}')
        else:
            if success_title and success_message:
                self.view.show_message_box_info(success_title, success_message)
            if on_success:
                on_success()

    def button_click_test_trade_post(self):
        from config import test_trade_data
        post_string = self.generate_trade_post_string(**test_trade_data)
        self.copy_to_clipboard(post_string, 'Generated!', f'This is what your trade post looks like:\n{post_string}')

    def button_click_test_wine_unload(self):
        from config import test_wine_unload_data
        post_string = self.generate_wine_unload_post_string(**test_wine_unload_data)
        try:
            pyperclip.copy(post_string)
        except pyperclip.PyperclipException as e:
            self.view.show_message_box_warning('Error', f'Error while copying to clipboard\n{e}')
        else:
            self.copy_to_clipboard(post_string, 'Generated!', f'This is what your wine unload post looks like:\n{post_string}')

    def button_click_test_discord_webhook(self):
        try:
            self.webhook_handler.send_message_with_embed('Test', 'If you see this, the webhook is working')
        except Exception as e:
            self.view.show_message_box_warning('Error', f'Error while sending discord webhook\n{e}')
        else:
            self.view.show_message_box_info('Success!', 'Test message sent to discord')

    def button_click_test_discord_webhook_ping(self):
        try:
            self.webhook_handler.send_message_with_embed('', '', image_url='https://c.tenor.com/HwA2vshx6AgAAAAd/tenor.gif', ping=True)
        except Exception as e:
            self.view.show_message_box_warning('Error', f'Error while sending discord ping\n{e}')
        else:
            self.view.show_message_box_info('Success!', 'Test message sent to discord with ping')
    
    def button_click_manual_timer(self):
        selected_row = self.get_selected_row()
        if selected_row is not None:
            carrierID = self.model.sorted_ids_display()[selected_row]
            self.manual_timer_view = ManualTimerView(self.view.root, carrierID=carrierID)
            reg = self.manual_timer_view.popup.register(checkTimerFormat)
            self.manual_timer_view.entry_timer.configure(validate='focusout', validatecommand=(reg, '%s'))
            self.manual_timer_view.button_post.configure(command=self.button_click_manual_timer_post)
        else:
            self.view.show_message_box_warning('Warning', 'Please select one carrier and one carrier only!')
    
    def button_click_clear_timer(self):
        selected_rows = self.get_selected_row(allow_multiple=True)
        if selected_rows is not None:
            for row in selected_rows:
                carrierID = self.model.sorted_ids_display()[row]
                if carrierID in self.model.manual_timers:
                    self.model.manual_timers.pop(carrierID)
        else:
            self.view.show_message_box_warning('Warning', 'Please select at least one carrier!')

    def button_click_manual_timer_post(self):
        if self.manual_timer_view.entry_timer.validate():
            carrierID = self.manual_timer_view.carrierID
            timer = self.manual_timer_view.entry_timer.get()
            timer = datetime.strptime(timer, '%H:%M:%S').replace(tzinfo=timezone.utc).time()
            timer = datetime.combine(date.today(), timer, tzinfo=timezone.utc)
            if timer < datetime.now(timezone.utc):
                timer += timedelta(days=1)
            assert timer > datetime.now(timezone.utc), f'Timer must be in the future, {timer}, {datetime.now(timezone.utc)}'
            if len(self.model.manual_timers) == 0:
                self.view.root.after(REMIND_INTERVAL, self.check_manual_timer)
            self.model.manual_timers[carrierID] = {'time': timer, 'reminded': False, 'plot_warned': False}
            self.manual_timer_view.popup.destroy()
    
    def button_click_post_departure(self):
        selected_row = self.get_selected_row()
        if selected_row is not None:
            carrierID = self.model.sorted_ids_display()[selected_row]
            system_current = self.model.get_current_system(carrierID=carrierID)
            system_dest = self.model.get_destination_system(carrier_ID=carrierID)
            carrier_name = self.model.get_name(carrierID)
            carrier_callsign = self.model.get_callsign(carrierID)
            hammer_countdown = self.model.get_departure_hammer_countdown(carrierID)
            if system_dest is not None:
                if system_dest in ['HIP 57784','HD 104495','HD 105341','HIP 58832'] and system_current in ['HIP 57784','HD 104495','HD 105341','HIP 58832']:
                    system_dest = f'{ladder_systems[system_dest]} ({system_dest})'
                    system_current = f'{ladder_systems[system_current]} ({system_current})'
                    # /wine_carrier_departure carrier_id:xxx-xxx departure_location:Gali arrival_location:N2 departing_at:<t:1733359620>
                    s = f'/wine_carrier_departure carrier_id:{carrier_callsign} departure_location:{system_current} arrival_location:{system_dest} departing_at:{hammer_countdown}'
                    self.copy_to_clipboard(s, 'Success!', f'Departure command for {carrier_name} ({carrier_callsign}) going {system_current} -> {system_dest} copied!')
                else:
                    self.view.show_message_box_warning('Warning', 'Only movements to and from N3 and up are supported')
            else:
                self.view.show_message_box_warning('Warning', f'{carrier_name} ({carrier_callsign}) doesn\'t have a jump plotted')
        else:
            self.view.show_message_box_warning('Warning', 'Please select one carrier and one carrier only!')
        
    def check_manual_timer(self):
        now = datetime.now(timezone.utc)
        for carrierID in self.model.sorted_ids():
            timer = self.model.manual_timers.get(carrierID, None)
            if timer is None:
                continue
            if timer['time'] <= now:
                self.model.manual_timers.pop(carrierID)
                continue
            elif timer['time'] - PLOT_WARN <= now and not timer['plot_warned']:
                timer['plot_warned'] = True
                m, s = divmod(PLOT_WARN.total_seconds(), 60)
                self.view.show_message_box_info('Plot imminent!', f'Plot {self.model.get_name(carrierID)} ({self.model.get_callsign(carrierID)}) in {m:02.0f} m {s:02.0f} s')
            elif timer['time'] - PLOT_REMIND <= now and not timer['reminded']:
                timer['reminded'] = True
                m, s = divmod(PLOT_REMIND.total_seconds(), 60)
                self.view.show_message_box_info('Get ready!', f'Be ready to plot {self.model.get_name(carrierID)} ({self.model.get_callsign(carrierID)}) in {m:02.0f} m {s:02.0f} s')
        if len(self.model.manual_timers) > 0:
            self.view.root.after(REMIND_INTERVAL, self.check_manual_timer)
    
    def redraw_fast(self):
        try:
            now = datetime.now(timezone.utc)
            self.update_tables_fast(now)
            self.update_time(now)
        except Exception as e:
            if self.view.show_message_box_askretrycancel('Error', f'An error occurred\n{traceback.format_exc()}'):
                self.view.root.after(REDRAW_INTERVAL_FAST, self.redraw_fast)
            else:
                self.view.root.destroy()
        else:
            self.view.root.after(REDRAW_INTERVAL_FAST, self.redraw_fast)
    
    def redraw_slow(self):
        try:
            now = datetime.now(timezone.utc)
            self.update_tables_slow(now)
        except Exception as e:
            if self.view.show_message_box_askretrycancel('Error', f'An error occurred\n{traceback.format_exc()}'):
                self.view.root.after(REDRAW_INTERVAL_SLOW, self.redraw_slow)
            else:
                self.view.root.destroy()
        else:
            self.view.root.after(REDRAW_INTERVAL_SLOW, self.redraw_slow)

    def get_selected_row(self, sheet=None, allow_multiple:bool=False) -> int|tuple[int]:
        if sheet is None:
            sheet = self.view.sheet_jumps
        selected_rows = sheet.get_selected_rows(get_cells=False, get_cells_as_rows=True, return_tuple=True)
        if selected_rows:
            if allow_multiple:
                return selected_rows
            elif len(selected_rows) == 1:
                return selected_rows[0]
            else:
                return None
        else:
            return None