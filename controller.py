import json
import os
import sys
import threading
import time
from typing import Callable, TYPE_CHECKING
from realtime import PostgresChangesPayload, AsyncRealtimeClient, RealtimeSubscribeStates
import pyperclip
import re
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from webbrowser import open_new_tab
# from winotify import Notification TODO: for notification without popup
from datetime import datetime, timezone, timedelta, date
from os import makedirs, path, remove
from shutil import copyfile
from tkinter import Tk
import traceback
import tomllib
import pickle
import asyncio
import pandas as pd
from string import Template
from playsound3 import playsound
from tkinter import Tk
from pystray import Icon, Menu, MenuItem
from PIL import Image
from supabase import FunctionsHttpError
from humanize import naturaltime
from concurrent.futures import ThreadPoolExecutor
from numpy import datetime64
from auth import AuthHandler
from settings import Settings, SettingsValidationError
from model import CarrierModel
from view import CarrierView, TradePostView, ManualTimerView
from station_parser import EDSMError, getStations
from utility import getHammerCountdown, checkTimerFormat, getTimerStatDescription, getCurrentVersion, getLatestVersion, getPrereleaseUpdateVersion, getResourcePath, isOnPrerelease, isUpdateAvailable, getSettingsPath, getSettingsDefaultPath, getSettingsDir, getAppDir, getCachePath, open_file, getInfoHash, getExpectedJumpTimer
from decos import debounce
from discord_handler import DiscordWebhookHandler
from time_checker import TimeChecker
from config import PLOT_WARN, UPDATE_INTERVAL, UPDATE_INTERVAL_TIMER_STATS, REDRAW_INTERVAL_FAST, REDRAW_INTERVAL_SLOW, REMIND_INTERVAL, PLOT_REMIND, SAVE_CACHE_INTERVAL, ladder_systems, SUPABASE_URL, SUPABASE_KEY

if TYPE_CHECKING: 
    import tksheet

class JournalEventHandler(FileSystemEventHandler):
    def __init__(self, controller: 'CarrierController'):
        self.controller = controller
    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith('.log'):
            self.controller._schedule_journal_update()
    on_created = on_modified

class CarrierController:
    def __init__(self, root:Tk, model:CarrierModel):
        self.root = root
        self.model = model
        self.tray_icon = None
        self.notification_settings = {}
        self.notification_settings_carrier = {}
        self.webhook_handler = None
        self.webhook_handler_carrier = {}
        self.auth_handler = AuthHandler()
        self.view = CarrierView(root)
        self.model.register_status_change_callback(self.status_change)
        self.load_settings(getSettingsPath())
        self.timer_stats = {"avg_timer": None, "count": 0, "earliest": None, "latest": None, 'slope': None}

        self.view.button_get_hammer.configure(command=self.button_click_hammer)
        self.view.button_post_trade.configure(command=self.button_click_post_trade)
        self.view.button_manual_timer.configure(command=self.button_click_manual_timer)
        self.view.button_clear_timer.configure(command=self.button_click_clear_timer)
        self.view.button_post_departure.configure(command=self.button_click_post_departure)
        self.view.button_post_trade_trade.configure(command=self.button_click_post_trade_trade)
        self.view.checkbox_filter_ghost_buys_var.trace_add('write', lambda *args: self.settings.set_config('Trade', 'filter_ghost_buys', value=self.view.checkbox_filter_ghost_buys_var.get()))
        self.view.button_open_journal.configure(command=self.button_click_open_journal)
        self.view.button_open_journal_folder.configure(command=self.button_click_open_journal_folder)
        self.view.button_check_updates.configure(command=lambda: self.check_app_update(notify_is_latest=True))
        self.view.button_reload_settings.configure(command=self.button_click_reload_settings)
        self.view.button_open_settings.configure(command=lambda: open_file(getSettingsPath()))
        self.view.button_reset_settings.configure(command=self.button_click_reset_settings)
        self.view.button_open_settings_dir.configure(command=lambda: open_file(getSettingsDir()))
        self.view.button_test_trade_post.configure(command=self.button_click_test_trade_post)
        self.view.button_test_wine_unload.configure(command=self.button_click_test_wine_unload)
        self.view.button_test_discord.configure(command=self.button_click_test_discord_webhook)
        self.view.button_test_discord_ping.configure(command=self.button_click_test_discord_webhook_ping)
        self.view.button_clear_cache.configure(command=self.button_click_clear_cache)
        self.view.button_go_to_github.configure(command=lambda: open_new_tab(url='https://github.com/skywalker-elite/Elite-Dangerous-Carrier-Manager'))
        self.view.button_check_time_skew.configure(command=lambda: self.check_time_skew(silent=False))
        self.view.checkbox_show_active_journals_var.trace_add('write', lambda *args: self.settings.set_config('UI', 'show_active_journals_tab', value=self.view.checkbox_show_active_journals_var.get()))
        self.view.checkbox_minimize_to_tray_var.trace_add('write', lambda *args: self.settings.set_config('UI', 'minimize_to_tray', value=self.view.checkbox_minimize_to_tray_var.get()))
        self.view.checkbox_minimize_to_tray.configure(command=lambda: self.setup_tray_icon())
        self.view.checkbox_enable_timer_reporting_var.trace_add('write', lambda *args: self.settings.set_config('timer_reporting', 'enabled', value=self.view.checkbox_enable_timer_reporting_var.get()))
        self.view.button_login.configure(command=self.button_click_login)
        self.view.button_report_timer_history.configure(command=self.button_click_report_timer_history)
        self.view.button_verify_roles.configure(command=self.button_click_verify_roles)
        self.view.button_delete_account.configure(command=self.button_click_delete_account)

        # initial load
        self.update_journals()

        self._observer = Observer()
        handler = JournalEventHandler(self)
        for jp in self.model.journal_paths:
            watch_dir = jp if os.path.isdir(jp) else os.path.dirname(jp)
            self._observer.schedule(handler, watch_dir, recursive=False)
        self._observer.daemon = True
        self._observer.start()

        # check time skew
        self.time_checker = TimeChecker()
        self.check_time_skew()

        self.set_current_version()
        self.redraw_fast()
        self.redraw_slow()
        threading.Thread(target=self.update_timer_stat_loop, daemon=True).start()
        self.view.update_table_active_journals(self.model.get_data_active_journals())
        # self._start_realtime_listener()
        self.check_app_update()
        self.minimize_hint_sent = False

        threading.Thread(target=self.save_cache).start()

        if self.auth_handler.is_logged_in():
            self.on_sign_in(show_message=False)
        else:
            self.on_sign_out(show_message=False)

        self.auth_handler.register_auth_event_callback('SIGNED_IN', lambda: self.root.after(0, self.on_sign_in))
        self.auth_handler.register_auth_event_callback('SIGNED_OUT', lambda: self.root.after(0, self.on_sign_out))

        self.save_window_size_on_resize()

    def _schedule_journal_update(self):
        # coalesce rapid events
        if getattr(self, '_journal_update_pending', False):
            return
        self._journal_update_pending = True
        self.view.root.after(0, self._perform_journal_update)

    def _perform_journal_update(self):
        self._journal_update_pending = False
        self.update_journals()
        self.view.update_table_active_journals(self.model.get_data_active_journals())

    def set_current_version(self):
        self.view.label_version.configure(text=getCurrentVersion())
    
    def check_app_update(self, notify_is_latest:bool=False):
        if isUpdateAvailable():
            if isOnPrerelease():
                version_latest = getPrereleaseUpdateVersion()
            else:
                version_latest = getLatestVersion()
            prompt = f'New version available: {version_latest}\nGo to download?'
            if self.view.show_message_box_askyesno('Update Available', prompt):
                if isOnPrerelease():
                    url = f'https://github.com/skywalker-elite/Elite-Dangerous-Carrier-Manager/releases/tag/{version_latest}'
                else:
                    url = 'https://github.com/skywalker-elite/Elite-Dangerous-Carrier-Manager/releases/latest'
                open_new_tab(url=url)
        elif notify_is_latest:
            version_current = getCurrentVersion()
            self.view.show_message_box_info('No update available', f'You are using the latest version: {version_current}')
    
    def load_settings(self, settings_file:str):
        if not os.path.exists(settings_file):
            if settings_file == getSettingsDefaultPath():
                raise FileNotFoundError(f'Default settings file not found at {settings_file}')
            else:
                if self.view.show_message_box_askyesno('Settings file not found', 'Do you want to create a new settings file?'):
                    try:
                        makedirs(getAppDir(), exist_ok=True)
                    except Exception as e:
                        self.view.show_message_box_warning('Error', f'Could not create app directory:\n{e}')
                    try:
                        copyfile(getSettingsDefaultPath(), settings_file)
                    except Exception as e:
                        self.view.show_message_box_warning('Error', f'Could not copy default settings file:\n{e}')
                    if self.view.show_message_box_askyesno('Success!', 'Settings file created using default settings. \nDo you want to edit it now?'):
                        try:
                            open_file(settings_file)
                        except Exception as e:
                            self.view.show_message_box_warning('Error', f'Could not open settings file:\n{e}')
                        self.view.show_message_box_info_no_topmost('Waiting', 'Click OK when you are done editing and saved the file')
                else:
                    self.view.show_message_box_info('Settings', 'Using default settings')
                    settings_file=getSettingsDefaultPath()
        try:
            self.settings = Settings(settings_file=settings_file)
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
            self.notification_settings = dict(self.settings.get('notifications'))
            self.notification_settings.update(dict(self.settings.get('discord')))
            self.webhook_handler = DiscordWebhookHandler(self.notification_settings.get('webhook'), self.notification_settings.get('userID'))
            self.webhook_handler_public = DiscordWebhookHandler(self.notification_settings.get('webhook_public'), self.notification_settings.get('userID'))
            for override in self.settings.get('advanced', 'carrier_notification_overrides'):
                for callsign in override:
                    print(f'Applying notification overrides for carrier {callsign}')
                    print(override[callsign])
                    carrier_notification_settings = self.notification_settings.copy()
                    for key, value in override[callsign].items():
                        if key in carrier_notification_settings:
                            carrier_notification_settings[key] = value
                        elif key == 'notify_while_ignored':
                            # special case, not part of notification settings
                            pass
                        else:
                            print(f'Warning: unknown setting {key} in override for carrier {callsign}')
                            self.view.show_message_box_warning('Warning', f'Unknown setting {key} in override for carrier {callsign}')
                    self.notification_settings_carrier[callsign] = carrier_notification_settings
                    if carrier_notification_settings.get('webhook') != self.notification_settings.get('webhook') or carrier_notification_settings.get('userID') != self.notification_settings.get('userID'):
                        self.webhook_handler_carrier[callsign] = DiscordWebhookHandler(carrier_notification_settings.get('webhook'), carrier_notification_settings.get('userID'))
                        self.webhook_handler_carrier[callsign + '_public'] = DiscordWebhookHandler(carrier_notification_settings.get('webhook_public'), carrier_notification_settings.get('userID'))
            self.apply_settings_to_model()
            self.view.set_font_size(self.settings.get('font_size', 'UI'), self.settings.get('font_size', 'table'))
            self.root.geometry(self.settings.get('UI', 'window_size'))
            self.view.checkbox_filter_ghost_buys_var.set(self.settings.get('Trade', 'filter_ghost_buys'))
            self.view.checkbox_show_active_journals_var.set(self.settings.get('UI', 'show_active_journals_tab'))
            self.view.checkbox_minimize_to_tray_var.set(self.settings.get('UI', 'minimize_to_tray'))
            self.setup_tray_icon()

    def apply_settings_to_model(self):
        self.model.reset_ignore_list()
        self.model.reset_sfc_whitelist()
        self.model.add_sfc_whitelist(self.settings.get('squadron_carriers', 'whitelist'))
        self.model.add_ignore_list(self.settings.get('advanced', 'ignore_list'))
        self.model.reset_notify_while_ignored_list()
        for override in self.settings.get('advanced', 'carrier_notification_overrides'):
            for callsign in override:
                if override[callsign].get('notify_while_ignored', False):
                    self.model.add_notify_while_ignored_list(callsign)
        self.model.set_custom_order(self.settings.get('advanced', 'custom_order'))
        self.model.set_squadron_abbv_mapping(self.settings.get('name_customization', 'squadron_abbv'))
        self.model.read_journals() # re-read journals to apply ignore list and custom order
    
    def status_change(self, carrierID:int, status_old:str, status_new:str):
        # print(f'{self.model.get_name(carrierID)} ({self.model.get_callsign(carrierID)}) status changed from {status_old} to {status_new}')
        callsign = self.model.get_callsign(carrierID)
        notification_settings = self.notification_settings_carrier.get(callsign, self.notification_settings)
        carrier_webhook_handler: DiscordWebhookHandler = self.webhook_handler_carrier.get(callsign, self.webhook_handler)
        carrier_webhook_handler_public: DiscordWebhookHandler = self.webhook_handler_carrier.get(callsign + '_public', self.webhook_handler_public)
        if status_new == 'jumping':
            # jump plotted
            # print(f'{self.model.get_name(carrierID)} ({self.model.get_callsign(carrierID)}) plotted jump to {self.model.get_destination_system(carrierID)} body {self.model.get_destination_body(carrierID)}')
            if notification_settings.get('jump_plotted'):
                self.view.show_non_blocking_info('Jump plotted', f'{self.model.get_name(carrierID)} ({self.model.get_callsign(carrierID)}) plotted jump to {self.model.get_destination_system(carrierID, use_custom_name=True)} body {self.model.get_destination_body(carrierID)}')
            if notification_settings.get('jump_plotted_sound'):
                self.play_sound(notification_settings.get('jump_plotted_sound_file'))
            censor_mode = self.model.get_current_system(carrierID) in ['HD 105341','HIP 58832'] or self.model.get_destination_system(carrierID) in ['HD 105341','HIP 58832']
            if notification_settings.get('jump_plotted_discord'):
                carrier_webhook_handler.send_jump_status_embed(
                    status='jump_plotted', name=self.model.get_name(carrierID), callsign=self.model.get_callsign(carrierID), 
                    current_system=self.model.get_current_system(carrierID, use_custom_name=True), current_body=self.model.get_current_body(carrierID),
                    other_system=self.model.get_destination_system(carrierID, use_custom_name=True), other_body=self.model.get_destination_body(carrierID),
                    timestamp=None if censor_mode else self.model.get_departure_hammer_countdown(carrierID), ping=notification_settings.get('jump_plotted_discord_ping'))
            if notification_settings.get('jump_plotted_discord_public'):
                if not censor_mode:
                    carrier_webhook_handler_public.send_jump_status_embed(
                        status='jump_plotted', name=self.model.get_name(carrierID), callsign=self.model.get_callsign(carrierID), 
                        current_system=self.model.get_current_system(carrierID, use_custom_name=True), current_body=self.model.get_current_body(carrierID),
                        other_system=self.model.get_destination_system(carrierID, use_custom_name=True), other_body=self.model.get_destination_body(carrierID),
                        timestamp=self.model.get_departure_hammer_countdown(carrierID), ping=notification_settings.get('jump_plotted_discord_public_ping'))
            if self.settings.get('timer_reporting', 'enabled'):
                self.report_jump_timer(carrierID)
        elif status_new == 'cool_down':
            # jump completed
            # print(f'{self.model.get_name(carrierID)} ({self.model.get_callsign(carrierID)}) has arrived at {self.model.get_current_system(carrierID)} body {self.model.get_current_body(carrierID)}')
            if notification_settings.get('jump_completed'):
                self.view.show_non_blocking_info('Jump completed', f'{self.model.get_name(carrierID)} ({self.model.get_callsign(carrierID)}) has arrived at {self.model.get_current_system(carrierID, use_custom_name=True)} body {self.model.get_current_body(carrierID)}')
            if notification_settings.get('jump_completed_sound'):
                self.play_sound(notification_settings.get('jump_completed_sound_file'))
            censor_mode = self.model.get_current_system(carrierID) in ['HD 105341','HIP 58832'] or self.model.get_previous_system(carrierID) in ['HD 105341','HIP 58832']
            if notification_settings.get('jump_completed_discord'):
                carrier_webhook_handler.send_jump_status_embed(
                    status='jump_completed', name=self.model.get_name(carrierID), callsign=self.model.get_callsign(carrierID), 
                    current_system=self.model.get_current_system(carrierID, use_custom_name=True), current_body=self.model.get_current_body(carrierID),
                    other_system=self.model.get_previous_system(carrierID, use_custom_name=True), other_body=self.model.get_previous_body(carrierID),
                    timestamp=self.model.get_cooldown_hammer_countdown(carrierID), ping=notification_settings.get('jump_completed_discord_ping'))
            if notification_settings.get('jump_completed_discord_public'):
                if not censor_mode:
                    carrier_webhook_handler_public.send_jump_status_embed(
                        status='jump_completed', name=self.model.get_name(carrierID), callsign=self.model.get_callsign(carrierID), 
                        current_system=self.model.get_current_system(carrierID, use_custom_name=True), current_body=self.model.get_current_body(carrierID),
                        other_system=self.model.get_previous_system(carrierID, use_custom_name=True), other_body=self.model.get_previous_body(carrierID),
                        timestamp=self.model.get_cooldown_hammer_countdown(carrierID), ping=notification_settings.get('jump_completed_discord_public_ping'))
        elif status_new == 'cool_down_cancel':
            # jump cancelled
            # print(f'{self.model.get_name(carrierID)} ({self.model.get_callsign(carrierID)}) cancelled a jump')
            if notification_settings.get('jump_cancelled'):
                self.view.show_non_blocking_info('Jump cancelled', f'{self.model.get_name(carrierID)} ({self.model.get_callsign(carrierID)}) cancelled a jump')
            if notification_settings.get('jump_cancelled_sound'):
                self.play_sound(notification_settings.get('jump_cancelled_sound_file'))
            censor_mode = self.model.get_current_system(carrierID) in ['HD 105341','HIP 58832'] or self.model.get_previous_system(carrierID) in ['HD 105341','HIP 58832']
            if notification_settings.get('jump_cancelled_discord'):
                carrier_webhook_handler.send_jump_status_embed(
                    status='jump_cancelled', name=self.model.get_name(carrierID), callsign=self.model.get_callsign(carrierID), 
                    current_system=self.model.get_current_system(carrierID, use_custom_name=True), current_body=self.model.get_current_body(carrierID),
                    other_system=None, other_body=None,
                    timestamp=self.model.get_cooldown_cancel_hammer_countdown(carrierID), ping=notification_settings.get('jump_cancelled_discord_ping'))
            if notification_settings.get('jump_cancelled_discord_public'):
                if not censor_mode:
                    carrier_webhook_handler_public.send_jump_status_embed(
                        status='jump_cancelled', name=self.model.get_name(carrierID), callsign=self.model.get_callsign(carrierID), 
                        current_system=self.model.get_current_system(carrierID, use_custom_name=True), current_body=self.model.get_current_body(carrierID),
                        other_system=None, other_body=None,
                        timestamp=self.model.get_cooldown_cancel_hammer_countdown(carrierID), ping=notification_settings.get('jump_cancelled_discord_public_ping'))
        elif status_new == 'idle' and status_old in ['cool_down', 'cool_down_cancel']:
            # cool down complete
            # print(f'{self.model.get_name(carrierID)} ({self.model.get_callsign(carrierID)}) has finished cool down and is ready to jump')
            if notification_settings.get('cooldown_finished'):
                self.view.show_non_blocking_info('Cool down complete', f'{self.model.get_name(carrierID)} ({self.model.get_callsign(carrierID)}) has finished cool down and is ready to jump')
            if notification_settings.get('cooldown_finished_sound'):
                self.play_sound(notification_settings.get('cooldown_finished_sound_file'))
            censor_mode = self.model.get_current_system(carrierID) in ['HD 105341','HIP 58832']
            if notification_settings.get('cooldown_finished_discord'):
                carrier_webhook_handler.send_jump_status_embed(
                    status='cooldown_finished', name=self.model.get_name(carrierID), callsign=self.model.get_callsign(carrierID), 
                    current_system=self.model.get_current_system(carrierID, use_custom_name=True), current_body=self.model.get_current_body(carrierID),
                    other_system=None, other_body=None,
                    timestamp=self.model.get_cooldown_hammer_countdown(carrierID) if status_old == 'cool_down' else self.model.get_cooldown_cancel_hammer_countdown(carrierID) if status_old == 'cool_down_cancel' else None, 
                    ping=notification_settings.get('cooldown_finished_discord_ping'))
            if notification_settings.get('cooldown_finished_discord_public'):
                if not censor_mode:
                    carrier_webhook_handler_public.send_jump_status_embed(
                        status='cooldown_finished', name=self.model.get_name(carrierID), callsign=self.model.get_callsign(carrierID), 
                        current_system=self.model.get_current_system(carrierID, use_custom_name=True), current_body=self.model.get_current_body(carrierID),
                        other_system=None, other_body=None,
                        timestamp=self.model.get_cooldown_hammer_countdown(carrierID) if status_old == 'cool_down' else self.model.get_cooldown_cancel_hammer_countdown(carrierID) if status_old == 'cool_down_cancel' else None, 
                        ping=notification_settings.get('cooldown_finished_discord_public_ping'))

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
        self.view.update_table_trade(*self.model.get_data_trade(filter_ghost_buys=self.view.checkbox_filter_ghost_buys_var.get())) #TODO: reduce update rate for performance
        self.view.update_table_services(self.model.get_data_services(), pending_decom) #TODO: reduce update rate for performance
        self.view.update_table_misc(self.model.get_data_misc(), pending_decom) #TODO: reduce update rate for performance

    def update_time(self, now):
        self.view.update_time(now.strftime('%H:%M:%S'))

    def update_timer_stat_loop(self):
        while True:
            self.update_timer_stat()
            time.sleep(UPDATE_INTERVAL_TIMER_STATS / 1000)

    def update_timer_stat(self, payload:PostgresChangesPayload|None=None):
        print('Updating timer stats')
        self.timer_stats["avg_timer"], self.timer_stats["count"], self.timer_stats["earliest"], self.timer_stats["latest"], self.timer_stats["slope"] = getExpectedJumpTimer()
    
    def update_journals(self):
        try:
            self.model.read_journals()  # Re-read journals and update model's data
        except Exception as e:
            if self.view.show_message_box_askretrycancel('Error', f'An error occurred during journal update\n{traceback.format_exc()}'):
                self.view.root.after(UPDATE_INTERVAL, self.update_journals)
            else:
                self.view.root.destroy()
    
    def check_time_skew(self, silent: bool = True):
        if not silent:
            progress_win, progress_bar = self.view.show_indeterminate_progress_bar('Checking time skew', 'Checking system time against game server...')
        executioner = ThreadPoolExecutor(max_workers=1)
        future_skew = executioner.submit(self.time_checker.check_and_warn)
        def handle_skew_result(future):
            if not silent:
                    progress_win.destroy()
            try:
                warn, message = future.result()
                print(message)
                if warn:
                    self.view.show_message_box_warning('Time Skew Warning', message)
                elif not silent:
                    self.view.show_message_box_info('Time Skew Check', message)
            except Exception as e:
                print(f'Error checking time skew: {e}')
                if not silent:
                    self.view.show_message_box_warning('Time Skew Check Error', f'Error checking time skew:\n{e}')

        future_skew.add_done_callback(handle_skew_result)
    
    def button_click_hammer(self):
        selected_row = self.get_selected_row()
        if selected_row is not None:
            carrierID = self.model.sorted_ids_display()[selected_row]
            carrier_name = self.model.get_name(carrierID)
            carrier_callsign = self.model.get_callsign(carrierID)
            hammer_countdown = self.model.get_departure_hammer_countdown(carrierID)
            if hammer_countdown is not None:
                timestamp = datetime.fromtimestamp(int(''.join(c for c in hammer_countdown if c.isdigit())), timezone.utc)
                self.copy_to_clipboard(hammer_countdown, 'Success!', f'Hammertime countdown for {carrier_name} ({carrier_callsign}) ({naturaltime(timestamp)}) copied!')
            else:
                self.view.show_message_box_warning('Error', f'No jump data found for {carrier_name} ({carrier_callsign})')
        else:
            hammer_countdown = getHammerCountdown(datetime64(datetime.now(timezone.utc).replace(tzinfo=None)))
            self.copy_to_clipboard(hammer_countdown, 'Success!', f'No carrier selected, hammertime countdown for current time copied!')

    def button_click_post_trade(self):
        selected_row = self.get_selected_row()
        self.handle_post_trade_logic(selected_row, self.model.sorted_ids_display(), self.view.sheet_jumps)

    def button_click_post_trade_trade(self):
        selected_row = self.get_selected_row(sheet=self.view.sheet_trade)
        self.handle_post_trade_logic(selected_row, self.model.trade_carrierIDs, self.view.sheet_trade)

    def handle_post_trade_logic(self, selected_row: int, carrier_ids: list[int], sheet: 'tksheet.Sheet'):
        if selected_row is not None:
            carrierID = carrier_ids[selected_row]
            carrier_name = self.model.get_name(carrierID)
            system = self.model.get_current_or_destination_system(carrierID)
            carrier_callsign = self.model.get_callsign(carrierID)
            docking, notorious = self.model.generate_info_docking_perm(carrierID)
            if docking not in ['All', 'Unknown']:
                self.view.show_message_box_warning('Warning', f'{carrier_name} ({carrier_callsign}) has docking permission set to {docking}, haulers may not be able to dock')
            if notorious == 'No':
                self.view.show_message_box_warning('Warning', f'{carrier_name} ({carrier_callsign}) does not allow notorious cmdrs, haulers may not be able to dock')
            
            if sheet.name == 'sheet_trade':
                trade_type, amount, commodity, price = self.view.sheet_trade.data[selected_row][1:5]
                trade_type = trade_type.lower()
                amount = float(amount.replace(',',''))
                amount = round(amount / 500) * 500 / 1000
                if amount % 1 == 0:
                    amount = int(amount)
                order: tuple[str, str, int | float, int] = (trade_type, commodity, amount, price)
            elif sheet.name == 'sheet_jumps':
                order = self.model.get_formatted_largest_order(carrierID=carrierID)
            else:
                raise RuntimeError(f'Unexpected sheet name: {sheet.name}')

            if system == 'HIP 58832':
                self.handle_peak_trade_logic(carrierID, carrier_name, system, carrier_callsign, order)
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
                        trade_post_view = TradePostView(self.view.root, carrier_name=carrier_name, trade_type=trade_type, commodity=commodity, stations=stations, pad_sizes=pad_sizes, system=system, amount=amount, market_ids=market_ids, market_updated=market_updated, price=price)
                        trade_post_view.button_post.configure(command=lambda: self.button_click_post(trade_post_view=trade_post_view, carrier_name=carrier_name, carrier_callsign=carrier_callsign, trade_type=trade_type, commodity=commodity, system=system, amount=amount))
                    else:
                        self.view.show_message_box_warning('No station', f'There are no stations in this system ({system})')
                else:
                    self.view.show_message_box_warning('No trade order', f'There is no trade order set for {carrier_name} ({carrier_callsign})')
        else:
            self.view.show_message_box_warning('Warning', f'please select one {"carrier" if sheet.name == "sheet_jumps" else "trade"} and one {"carrier" if sheet.name == "sheet_jumps" else "trade"} only!')

    def handle_peak_trade_logic(self, carrierID: int, carrier_name: str, system: str, carrier_callsign: str, order: tuple[str, str, int | float, int]|None):
        body_id = self.model.get_current_or_destination_body_id(carrierID=carrierID)
        planetary_body = {0: 'Star', 1: 'Planet 1', 2: 'Planet 2', 3: 'Planet 3', 4: 'Planet 4', 5: 'Planet 5', 16: 'Planet 6'}.get(body_id, None) # Yes, the body_id of Planet 6 is 16, don't ask me why
        if planetary_body is not None:
            timed_unload = self.view.show_message_box_askyesno('Timed unload?', 'Is this a timed unload? (Please follow STC instructions)')
            post_string = self.generate_wine_unload_post_string(carrier_callsign=carrier_callsign, planetary_body=planetary_body, timed_unload=timed_unload)
            self.copy_to_clipboard(post_string, 'It\'s wine o\'clock', f'{"Timed" if timed_unload else "Wine"} unload command copied')
            if order is None or (order[0] != 'unloading' or order[1] != 'Wine'): # no wine unload order
                if not timed_unload:
                    self.view.show_message_box_warning('Warning', 'You have not opened the market yet!\nMake sure to open the market before running the unload command!')
            else:
                if timed_unload:
                    self.view.show_message_box_warning('Warning', 'You have already opened the market!\nYou should close the market now and open it when it\'s time to unload.')
                _, _, _, price = order
                if not 21500 < price < 22500:
                    self.view.show_message_box_warning('Price warning', f'You are selling wine at a non-standard price ({price:,} Cr/ton)\nMake sure to follow the guidelines!')

    def button_click_post(self, trade_post_view: TradePostView, carrier_name:str, carrier_callsign:str, trade_type:str, commodity:str, system:str, amount:int|float):
        station = trade_post_view.cbox_stations.get()
        profit = trade_post_view.cbox_profit.get()
        pad_size = trade_post_view.cbox_pad_size.get()
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
        self.copy_to_clipboard(post_string, None, None, on_success=lambda: trade_post_view.popup.destroy())

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

    def generate_wine_unload_post_string(self, carrier_callsign:str, planetary_body:str, timed_unload:bool=False) -> str:
        if not timed_unload:
            s = Template(self.settings.get('post_format', 'wine_unload_string'))
            post_string = s.safe_substitute(carrier_callsign=carrier_callsign, planetary_body=planetary_body)
        else:
            s = Template(self.settings.get('post_format', 'wine_unload_timed_string'))
            post_string = s.safe_substitute(carrier_callsign=carrier_callsign, planetary_body=planetary_body)
        return post_string

    def copy_to_clipboard(self, text: str, success_title: str|None, success_message: str|None, on_success: Callable[[], None]|None=None):
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
        try:
            post_string = self.generate_trade_post_string(**test_trade_data)
        except Exception as e:
            self.view.show_message_box_warning('Error', f'Error while generating trade post string\n{e}')
        else:
            self.copy_to_clipboard(post_string, 'Generated!', f'This is what your trade post looks like:\n{post_string}')

    def button_click_test_wine_unload(self):
        from config import test_wine_unload_data
        try:
            post_string = self.generate_wine_unload_post_string(**test_wine_unload_data)
        except Exception as e:
            self.view.show_message_box_warning('Error', f'Error while generating wine unload post string\n{e}')
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
            if getattr(self, 'manual_timer_view', None) is not None:
                self.manual_timer_view.popup.destroy()
                self.manual_timer_view = None
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
            now_utc = datetime.now(timezone.utc)
            if timer < now_utc:
                timer += timedelta(days=1)
            assert timer > now_utc, f'Timer must be in the future, {timer}, {now_utc}'
            if timer - now_utc > timedelta(hours=1, minutes=15):
                if not self.view.show_message_box_askyesno('Warning', 'Timer set more than 1 hour 15 minutes in the future, are you sure?'):
                    return
            if len(self.model.manual_timers) == 0:
                self.view.root.after(REMIND_INTERVAL, self.check_manual_timer)
            self.model.manual_timers[carrierID] = {'time': timer, 'reminded': False, 'plot_warned': False}
            self.manual_timer_view.popup.destroy()
    
    def button_click_post_departure(self):
        selected_row = self.get_selected_row()
        if selected_row is not None:
            carrierID = self.model.sorted_ids_display()[selected_row]
            system_current = self.model.get_current_system(carrierID=carrierID)
            system_dest = self.model.get_destination_system(carrierID=carrierID)
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

    def button_click_open_journal(self):
        selected_row = self.get_selected_row(sheet=self.view.sheet_active_journals)
        if selected_row is not None:
            active_journal_paths = self.model.get_active_journal_paths()
            if not active_journal_paths:
                self.view.show_message_box_warning('Warning', 'No active journals found')
            else:
                journal_file = active_journal_paths[selected_row]
                open_file(journal_file)
        else:
            self.view.show_message_box_warning('Warning', 'Please select one row.')

    def button_click_open_journal_folder(self):
        selected_row = self.get_selected_row(sheet=self.view.sheet_active_journals)
        if selected_row is not None:
            active_journal_paths = self.model.get_active_journal_paths()
            if not active_journal_paths:
                self.view.show_message_box_warning('Warning', 'No active journals found')
            else:
                journal_file = active_journal_paths[selected_row]
                open_file(path.dirname(journal_file))
        else:
            self.view.show_message_box_warning('Warning', 'Please select one row.')

    def check_manual_timer(self):
        now = datetime.now(timezone.utc)
        remind = timedelta(seconds=self.settings.get('plot_reminders', 'remind_seconds'))
        warn = timedelta(seconds=self.settings.get('plot_reminders', 'warn_seconds'))
        clear = timedelta(seconds=self.settings.get('plot_reminders', 'clear_seconds'))
        for carrierID in self.model.sorted_ids():
            timer = self.model.manual_timers.get(carrierID, None)
            if timer is None:
                continue
            if timer['time'] + clear <= now:
                self.model.manual_timers.pop(carrierID)
                continue
            elif timer['time'] - warn <= now and not timer['plot_warned']:
                timer['plot_warned'] = True
                m, s = divmod(warn.total_seconds(), 60)
                self.view.show_message_box_info('Plot imminent!', f'Plot {self.model.get_name(carrierID)} ({self.model.get_callsign(carrierID)}) in {m:02.0f} m {s:02.0f} s')
            elif timer['time'] - remind <= now and not timer['reminded']:
                timer['reminded'] = True
                m, s = divmod(remind.total_seconds(), 60)
                self.view.show_message_box_info('Get ready!', f'Be ready to plot {self.model.get_name(carrierID)} ({self.model.get_callsign(carrierID)}) in {m:02.0f} m {s:02.0f} s')
        if len(self.model.manual_timers) > 0:
            self.view.root.after(REMIND_INTERVAL, self.check_manual_timer)
    
    def redraw_fast(self):
        try:
            now = datetime.now(timezone.utc)
            self.update_tables_fast(now)
            self.update_time(now)
            self.redraw_timer_stat()
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

    def redraw_timer_stat(self):
        self.view.update_timer_stat(getTimerStatDescription(self.timer_stats["avg_timer"], self.timer_stats["count"], self.timer_stats["earliest"], self.timer_stats["latest"], self.timer_stats["slope"]))

    # def _start_realtime_listener(self):
    #     self._realtime_loop = asyncio.new_event_loop()
    #     t = threading.Thread(target=self._realtime_loop.run_forever, daemon=True)
    #     t.start()
    #     asyncio.run_coroutine_threadsafe(self._realtime_handler(), self._realtime_loop)

    # async def _realtime_handler(self):
    #     url = f"{SUPABASE_URL}/realtime/v1"
    #     token = SUPABASE_KEY
    #     backoff = 1
    #     while True:
    #         try:
    #             client = AsyncRealtimeClient(url=url, token=token)
    #             ch = client.channel("public:jump_timers_public")
    #             ch.on_postgres_changes(
    #                 event="*", schema="public", table="jump_timers_public",
    #                 callback=self.update_timer_stat
    #             )
    #             await ch.subscribe(callback=self._subscription_state_change)
    #             print("Realtime subscription established")
    #             while client.is_connected:
    #                 await asyncio.sleep(1)
    #             raise RuntimeError("Realtime client disconnected")
    #         except Exception as e:
    #             print(f"[realtime] subscription error: {e}, reconnecting in {backoff}s…")
    #             await asyncio.sleep(backoff)
    #             backoff = min(backoff * 2, 30)

    # def _subscription_state_change(self, state: RealtimeSubscribeStates, exception: Exception | None):
    #     # just logging
    #     if state is RealtimeSubscribeStates.TIMED_OUT:
    #         print(f"Subscription timed out{f', exception={exception!r}' if exception else ''}")
    #     elif state in (RealtimeSubscribeStates.CLOSED, RealtimeSubscribeStates.CHANNEL_ERROR):
    #         print(f"Subscription closed{f', exception={exception!r}' if exception else ''}")
    #     elif state is RealtimeSubscribeStates.SUBSCRIBED:
    #         print("Subscription successful")
    #     else:
    #         print(f"Subscription state={state}, exception={exception!r}")

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
        
    def save_cache(self):
        cache_path = getCachePath(self.model.journal_reader.version, self.model.journal_reader.journal_paths)
        if cache_path is not None:
            makedirs(path.dirname(cache_path), exist_ok=True)
            try:
                self._save_cache(cache_path)
            except Exception as e:
                self.view.show_message_box_warning('Error', f'Error while saving cache\n{traceback.format_exc()}')
            else:
                self.view.root.after(SAVE_CACHE_INTERVAL, self.save_cache)
        else:
            self.view.show_message_box_warning('Warning', 'Cache path is not set, cannot save cache')

    def _save_cache(self, cache_path:str):
        if cache_path is not None:
            makedirs(path.dirname(cache_path), exist_ok=True)
            with open(cache_path, 'wb') as f:
                pickle.dump(self.model.journal_reader, f)

    def button_click_clear_cache(self):
        cache_path = getCachePath(self.model.journal_reader.version, self.model.journal_reader.journal_paths)
        if cache_path is not None and path.exists(cache_path):
            try:
                remove(cache_path)
            except Exception as e:
                self.view.show_message_box_warning('Error', f'Error while clearing cache\n{traceback.format_exc()}')
            else:
                self.view.show_message_box_info('Success!', 'Cache cleared, EDCM will reload all journals now')
                self.reload()
        else:
            self.view.show_message_box_info('Info', 'No cache file found')

    def reload(self):
        progress_win, progress_bar = self.view.show_indeterminate_progress_bar('Reloading', 'Reloading all journals, this may take a while depending on the size of your journals')
        thread_reload = threading.Thread(target=self._reload)
        thread_reload.start()
        while thread_reload.is_alive():
            progress_win.update()
            time.sleep(0.0001)
        progress_win.destroy()
        self.save_cache()

    def _reload(self):
        self.model = CarrierModel(journal_paths=self.model.journal_paths, journal_reader=None, dropout=self.model.dropout, droplist=self.model.droplist)
        self.model.register_status_change_callback(self.status_change)
        self.model.read_journals()
        self.apply_settings_to_model()

    def button_click_login(self):
        if not self.auth_handler.is_logged_in():
            threading.Thread(target=self.auth_handler.login, daemon=True).start()
        else:
            self.view.root.after(0, self.view.show_message_box_info, 'Info', f'Already logged in as {self.auth_handler.get_username()}')

    def button_click_logout(self):
        if self.auth_handler.is_logged_in():
            if self.view.show_message_box_askyesno('Logout', f'Do you want to logout of {self.auth_handler.get_username()}?'):
                threading.Thread(target=self.auth_handler.logout, daemon=True).start()
        else:
            self.view.show_message_box_info('Info', 'Not logged in')

    def button_click_verify_roles(self):
        in_ptn, roles = self.auth_handler.auth_PTN_roles()
        if in_ptn is None:
            self.view.show_message_box_warning('Error', 'Error while verifying roles, please try again later')
        elif not in_ptn:
            self.view.show_message_box_info('Not in PTN', 'You are not in the PTN Discord server, please make sure you are using the correct Discord account')
        elif not roles:
            self.view.show_message_box_info('Info', f'You are in the PTN, but have no elevated roles assigned.')
        else:
            roles_str = ', '.join(roles)
            self.view.show_message_box_info('Success!', f'You are in the PTN and have the following roles:\n {roles_str}')

    def button_click_delete_account(self):
        if self.auth_handler.is_logged_in():
            if self.view.show_message_box_askyesno('Delete Account', 'Are you sure you want to delete your account?\n'
                                                    'This action cannot be undone.'):
                if self.view.show_message_box_askyesno('Delete Account', 'This will also delete all your data, including all the jump timers you\'ve ever reported.\n'
                                                         'Are you really sure you want to delete your account?'):
                    try:
                        response = self.auth_handler.invoke_edge("delete-account")
                        if 'error' in response:
                            self.view.show_message_box_warning('Error', f"Error deleting account: {response['error']}")
                    except Exception as e:
                        self.view.show_message_box_warning('Error', f"Error deleting account: {e}")
                    else:
                        self.view.show_message_box_info('Success!', 'Your account and data has been deleted successfully')
                        self.auth_handler.logout()

    def on_sign_out(self, show_message: bool=True):
        if show_message:
            self.view.show_message_box_info('Logged Out', 'You have been logged out')
        self.view.button_login.configure(text='Login with Discord')
        self.view.button_login.configure(command=lambda: threading.Thread(target=self.button_click_login, daemon=True).start())
        self.view.checkbox_enable_timer_reporting.configure(state='disabled')
        # self.view.checkbox_enable_timer_reporting_var.set(False)
        self.view.button_verify_roles.configure(state='disabled')
        self.view.button_delete_account.configure(state='disabled')
        self.view.button_report_timer_history.configure(state='disabled')

    def on_sign_in(self, show_message: bool=True):
        if show_message:
            self.view.show_message_box_info('Logged In', f'You are now logged in as {self.auth_handler.get_username()}')
        self.view.button_login.configure(text=f'Logout of {self.auth_handler.get_username()}')
        self.view.button_login.configure(command=self.button_click_logout)
        self.view.checkbox_enable_timer_reporting.configure(state='normal')
        self.view.checkbox_enable_timer_reporting_var.set(self.settings.get('timer_reporting', 'enabled'))
        self.view.button_verify_roles.configure(state='normal')
        self.view.button_delete_account.configure(state='normal')
        self.view.button_report_timer_history.configure(state='normal')

    def report_jump_timer(self, carrierID:int):
        if self.model.get_current_system(carrierID) in ['HD 105341','HIP 58832'] or self.model.get_destination_system(carrierID) in ['HD 105341','HIP 58832']:
            print(f'Skipping jump timer report for N1 and N0')
            return
        if carrierID in self.model.get_ignore_list():
            print(f'Skipping jump timer report for ignored carrierID {carrierID}')
            return
        if self.auth_handler.is_logged_in():
            jump_plot_timestamp = self.model.get_latest_jump_plot(carrierID)
            latest_departure_time = self.model.get_latest_departure(carrierID)
            payload = self.generate_timer_payload(carrierID, jump_plot_timestamp, latest_departure_time)
            # Report the jump timer to the server
            try:
                response = self.auth_handler.invoke_edge("submit-report", body=payload)
                print('Report submitted successfully:', response)
            except Exception as e:
                print(f"Error reporting jump timer: {e}")

    def generate_timer_payload(self, carrierID:int, jump_plot_timestamp:datetime|None, latest_departure_time:datetime|None) -> dict:
        timer = self.model.get_jump_timer_in_seconds(jump_plot_timestamp, latest_departure_time)
        if timer is None:
            raise RuntimeError(f'Cannot generate timer payload, timer is None for {self.model.get_name(carrierID)} ({self.model.get_callsign(carrierID)})')
        payload = {
            "journal_timestamp": jump_plot_timestamp.isoformat(),
            "timer": timer,
            "info_hash": getInfoHash(journal_timestamp=jump_plot_timestamp, timer=timer, carrierID=carrierID)
        }
        return payload

    def generate_timer_history(self) -> pd.DataFrame:
        payloads = []
        for carrierID in self.model.sorted_ids_display():
            jumps: pd.DataFrame = self.model.get_carriers()[carrierID]['jumps']
            for _, jump in jumps.iterrows():
                jump_plot_timestamp = jump['timestamp']
                departure_time = jump.get('DepartureTime', None)
                if departure_time is None:
                    continue
                payload = self.generate_timer_payload(carrierID, jump_plot_timestamp, departure_time)
                payloads.append(payload)
        df = pd.DataFrame(payloads, columns=['journal_timestamp', 'timer', 'info_hash'])
        return df

    def report_timer_history(self) -> tuple[int|None, int|None, int|None]:
        if self.auth_handler.is_logged_in():
            df = self.generate_timer_history()
            if df.empty:
                return 0, None, None
            def _chunks(seq: list[dict[str, any]], size: int):
                for i in range(0, len(seq), size):
                    yield seq[i:i+size]
            totals = {"submitted": 0, "inserted": 0, "skipped": 0}
            for chunk in _chunks(df.to_dict(orient='records'), 500):
                response = self.auth_handler.invoke_edge("submit-bulk-report", body=chunk)
                if 'error' in response:
                    raise RuntimeError(f"Error reporting jump timer: {response.error}")
                if response.get('ok', None) is True:
                    totals['submitted'] += len(chunk)
                    totals['inserted'] += response.get('inserted', None)
                    totals['skipped'] += response.get('skipped', None)
                else:
                    print(f"Error reporting jump timer: {response}")
                    raise RuntimeError(f"Error reporting jump timer: {response}")
            return totals['submitted'], totals['inserted'], totals['skipped']
        return None, None, None

    def button_click_report_timer_history(self):
        if not self.auth_handler.is_logged_in():
            return self.view.show_message_box_warning('Not logged in', 'You need to be logged in to report timer history')
        if not self.auth_handler.can_bulk_report():
            return self.view.show_message_box_warning(
                'Permission denied',
                'You need certain PTN roles to report jump timer history.\n'
                'Use "Verify PTN Roles" to refresh your roles if you recently got promoted.\n'
                'If you think you should have access, please contact the developer: Skywalker.'
            )
        if not self.view.show_message_box_askyesno(
            'Report timer history',
            'Caution: This will report every jump you have ever made (except the ignored carriers), do you want to continue?'
        ):
            return

        # spawn a background thread so the UI stays responsive
        thread_report_history = threading.Thread(target=self._run_report_timer_history, daemon=True)
        thread_report_history.start()

    def _run_report_timer_history(self):
        try:
            submitted, inserted, skipped = self.report_timer_history()
            if submitted is None:
                box = 'warning'; title = 'Error'; msg = 'Error reporting jump timer history, please try again later'
            elif submitted > 0:
                box = 'info'; title = 'Success'; msg = f'Submitted {submitted} jump timers, {inserted} accepted, {skipped} skipped.'
            else:
                box = 'info'; title = 'No Data'; msg = 'No jump timers to report.'
        except FunctionsHttpError as e:
            if e.status == 429:
                box = 'warning'; title = 'Rate limited'; msg = 'You are being rate limited, please try again later'
            else:
                box = 'warning'; title = 'Error'; msg = f'Error reporting jump timer history\n{e.name} {e.status}: {e.message}'
        except Exception:
            box = 'warning'; title = 'Error'; msg = f'Error reporting jump timer history\n{traceback.format_exc()}'

        # back onto the Tk event loop to show the dialog
        self.view.root.after(0, lambda:
            getattr(self.view, f'show_message_box_{box}')(title, msg)
        )

    def setup_tray_icon(self):
        if self.view.checkbox_minimize_to_tray_var.get():
            if sys.platform in ['win32', 'linux']:
                if self.tray_icon is None:
                    icon = Icon(
                        'Elite Dangerous Carrier Manager',
                        Image.open(getResourcePath(path.join('images','EDCM.png'))),
                        'EDCM',
                        Menu(
                            MenuItem('Show', self._on_show, default=True),
                            MenuItem('Quit', self._on_quit)
                        )
                    )
                    self.tray_icon = icon
                    if self.tray_icon.HAS_MENU:
                        threading.Thread(target=self.tray_icon.run, daemon=True).start()
                        self.root.bind('<Unmap>', lambda e: self._on_minimize() if self.root.state() == 'iconic' else None)
                    else:
                        self.view.show_message_box_warning('Error', 'System tray not supported on this system, minimize to tray disabled\n \
                                                        for more information, check the FAQ on the GitHub page.')
                        self.tray_icon = None
                        self.view.checkbox_minimize_to_tray_var.set(False)
                else:
                    # tray icon already exists
                    pass
            else:
                self.view.show_message_box_warning('Error', 'System tray not supported on this system, minimize to tray disabled\n \
                                                for more information, check the FAQ on the GitHub page.')
                self.tray_icon = None
                self.view.checkbox_minimize_to_tray_var.set(False)
                self.view.checkbox_minimize_to_tray.config(state='disabled')
        else:
            if self.tray_icon is not None:
                self.tray_icon.stop()
                self.tray_icon = None
            self.root.unbind('<Unmap>')
            self.root.deiconify()

    def _on_show(self, icon, item):
        self.root.after(0, self.root.deiconify)

    def _on_quit(self, icon, item):
        icon.stop()
        self.root.after(0, self.root.destroy)

    def _on_minimize(self):
        self._send_to_tray()

    def _send_to_tray(self):
        if self.tray_icon.HAS_NOTIFICATION and not self.minimize_hint_sent:
            self.tray_icon.notify(
                'EDCM is still running. Click the tray icon to restore the window.',
                'EDCM Minimized to Tray'
            )
            self.minimize_hint_sent = True
        self.root.withdraw()

    def save_window_size_on_resize(self):
        self.root.bind('<Configure>', self._on_configure)

    @debounce(10)
    def _on_configure(self, event):
        print('Saving window size:', f'{self.root.winfo_width()}x{self.root.winfo_height()}')
        self.settings.set_config('UI', 'window_size', value=f'{self.root.winfo_width()}x{self.root.winfo_height()}')