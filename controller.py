import threading
import time
import pyperclip
import re
# from winotify import Notification TODO: for notification without popup
from datetime import datetime, timezone
from model import CarrierModel
from view import CarrierView, TradePostView, ManualTimerView
from station_parser import getStations
from utility import checkTimerFormat
from config import UPDATE_INTERVAL, REDRAW_INTERVAL, REMIND_INTERVAL, REMIND, ladder_systems

class CarrierController:
    def __init__(self, root, model:CarrierModel):
        self.model = model
        self.view = CarrierView(root)
        self.view.button_get_hammer.configure(command=self.button_click_hammer)
        self.view.button_post_trade.configure(command=self.button_click_post_trade)
        self.view.button_manual_timer.configure(command=self.button_click_manual_timer)
        self.view.button_post_departure.configure(command=self.button_click_post_departure)

        # Start the carrier update loop
        self.update_journals()

        # Start the UI update loop
        self.redraw()

    def update_table(self, now):
        self.model.update_carriers(now)
        self.view.update_table(self.model.get_data(now))
        self.view.update_table_finance(self.model.get_data_finance())
        self.view.update_table_trade(self.model.get_data_trade())
        self.view.update_table_services(self.model.get_data_services())
        self.view.update_table_misc(self.model.get_data_misc())

    def update_time(self, now):
        self.view.update_time(now.strftime('%H:%M:%S'))
    
    def update_journals(self):
        self.model.read_journals()  # Re-read journals and update model's data
        self.view.root.after(UPDATE_INTERVAL, self.update_journals)
    
    def button_click_hammer(self):
        selected_row = self.get_selected_row()
        if selected_row is not None:
            carrierID = self.model.sorted_ids()[selected_row]
            carrier_name = self.model.get_name(carrierID)
            carrier_callsign = self.model.get_callsign(carrierID)
            hammer_countdown = self.model.get_departure_hammer_countdown(carrierID)
            
            pyperclip.copy(hammer_countdown)
            self.view.show_message_box_info('Success!', f'Hammertime for {carrier_name} ({carrier_callsign}) Copied!')
        else:
            self.view.show_message_box_warning('Warning', 'please select one carrier and one carrier only!')

    def button_click_post_trade(self):
        selected_row = self.get_selected_row()
        if selected_row is not None:
            carrierID = self.model.sorted_ids()[selected_row]
            carrier_name = self.model.get_name(carrierID)
            system = self.model.get_current_or_destination_system(carrierID)
            # carrier_callsign = self.model.get_callsign(carrierID)

            if system == 'HIP 58832':
                last_order = self.model.get_formated_last_order(carrierID=carrierID)
                if last_order is not None:
                    trade_type, commodity, amount = last_order
                    #if trade_type == 'unloading' and commodity == 'Wine': # nvm this shouldn't even be a question
                    callsign = self.model.get_callsign(carrierID=carrierID)
                    body = self.model.get_current_or_destination_body(carrierID=carrierID)
                    if body != 'Star':
                        if body in ['1', '2', '3', '4', '5', '6']:
                            body = f'Planet {body}'
                    post_string = f'/wine_unload carrier_id: {callsign} planetary_body: {body} market_type: Open'
                    pyperclip.copy(post_string)
                    self.view.show_message_box_info('Wine o\'clock', 'Wine unload command copied')
            else:
                stations, pad_sizes = getStations(sys_name=system)
                if len(stations) > 0:
                    last_order = self.model.get_formated_last_order(carrierID=carrierID)
                    if last_order is not None:
                        trade_type, commodity, amount = last_order

                        self.trade_post_view = TradePostView(self.view.root, carrier_name=carrier_name, trade_type=trade_type, commodity=commodity, stations=stations, pad_sizes=pad_sizes, system=system, amount=amount)
                        self.trade_post_view.button_post.configure(command=lambda: self.button_click_post(carrier_name=carrier_name, trade_type=trade_type, commodity=commodity, system=system, amount=amount))
                    else:
                        self.view.show_message_box_warning('No trade order', 'There is no trade order set')
                else:
                    self.view.show_message_box_warning('No station', 'There are no stations in this system')
        else:
            self.view.show_message_box_warning('Warning', 'please select one carrier and one carrier only!')
    
    def button_click_post(self, carrier_name:str, trade_type:str, commodity:str, system:str, amount:int|float):
        # /cco load carrier:P.T.N. Rocinante commodity:Agronomic Treatment system:Leesti station:George Lucas profit:11 pads:L demand:24
        s = '/cco {trade_type} carrier:{carrier_name} commodity:{commodity} system:{system} station:{station} profit:{profit} pads:{pad_size} {demand_supply}: {amount}'
        station = self.trade_post_view.cbox_stations.get()
        profit = self.trade_post_view.cbox_profit.get()
        pad_size = self.trade_post_view.cbox_pad_size.get()
        match pad_size:
            case 'L':
                pad_size = 'Large'
            case 'M':
                pad_size = 'Medium'
            case _:
                raise RuntimeError(f'Unexpected pad_size: {pad_size}')

        post_string = s.format(trade_type=trade_type.replace('ing', ''), carrier_name=carrier_name, commodity=commodity, system=system, station=station, profit=profit, pad_size=pad_size, demand_supply='demand' if trade_type=='loading'else 'supply', amount=amount)
        pyperclip.copy(post_string)
        self.trade_post_view.popup.destroy()
    
    def button_click_manual_timer(self): # TODO
        self.manual_timer_view = ManualTimerView(self.view.root)
        reg = self.manual_timer_view.popup.register(checkTimerFormat)
        self.manual_timer_view.entry_timer.configure(validate='focusout', validatecommand=(reg, '%s'))
        self.manual_timer_view.button_post.configure(command=self.button_click_manual_timer_post)
        # selected_row = self.get_selected_row()
        # if selected_row is not None:
        #     carrierID = self.model.sorted_ids()[selected_row]
    
    def button_click_manual_timer_post(self):
        if self.manual_timer_view.entry_timer.validate():
            if len(self.model.manual_timers) == 0:
                self.view.root.after(REMIND_INTERVAL, self.check_manual_timer)
            self.model.manual_timers.append(self.manual_timer_view.entry_timer.get())
            self.manual_timer_view.popup.destroy()
    
    def button_click_post_departure(self):
        selected_row = self.get_selected_row()
        if selected_row is not None:
            carrierID = self.model.sorted_ids()[selected_row]
            system_current = self.model.get_current_system(carrierID=carrierID)
            system_dest = self.model.get_destination_system(carrier_ID=carrierID)
            carrier_name = self.model.get_name(carrierID)
            carrier_callsign = self.model.get_callsign(carrierID)
            hammer_countdown = self.model.get_departure_hammer_countdown(carrierID)
            if system_dest is not None:
                if system_dest in ['HIP 57784','HD 104495','HD 105341','HIP 58832'] and system_current in ['HIP 57784','HD 104495','HD 105341','HIP 58832']:
                    system_dest = ladder_systems[system_dest]
                    system_current = ladder_systems[system_current]
                    # /wine_carrier_departure carrier_id:xxx-xxx departure_location:Gali arrival_location:N2 departing_at:<t:1733359620>
                    s = f'/wine_carrier_departure carrier_id:{carrier_callsign} departure_location:{system_current} arrival_location:{system_dest} departing_at:{hammer_countdown}'
                    pyperclip.copy(s)
                    self.view.show_message_box_info('Success!', f'Departure command for {carrier_name} ({carrier_callsign}) going {system_current} -> {system_dest} copied!')
                else:
                    self.view.show_message_box_warning('Warning', 'Only movements to and from N3 and up are supported')
            else:
                self.view.show_message_box_warning('Warning', f'{carrier_name} ({carrier_callsign}) doesn\'t have a jump plotted')
        else:
            self.view.show_message_box_warning('Warning', 'Please select one carrier and one carrier only!')
        
    def check_manual_timer(self): # TODO: UI to show timers
        now = datetime.now(timezone.utc)
        in2min = (datetime.now(timezone.utc) + REMIND)
        for timer in self.model.manual_timers:
            m, s = divmod(REMIND.total_seconds(), 60)
            if timer == now.strftime('%H:%M:%S'):
                self.view.show_message_box_info('Plot now!', f'Plot now')
                self.model.manual_timers.remove(timer)
            elif timer == in2min.strftime('%H:%M:%S'):
                self.view.show_message_box_info('Get ready!', f'Be ready to plot in {m:02.0f} m {s:02.0f} s')
        if len(self.model.manual_timers) > 0:
            self.view.root.after(REMIND_INTERVAL, self.check_manual_timer)
    
    def redraw(self):
        now = datetime.now(timezone.utc)
        self.update_table(now)
        self.update_time(now)
        self.view.root.after(REDRAW_INTERVAL, self.redraw)

    def get_selected_row(self):
        selected = self.view.sheet.selected
        if selected:
            if selected.box.from_r == selected.box.upto_r - 1:
                return selected.box.from_r
            else:
                return None
        else:
            return None