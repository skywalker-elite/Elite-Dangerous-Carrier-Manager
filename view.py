import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
from tksheet import Sheet
from typing import Literal
from config import WINDOW_SIZE_TIMER

class CarrierView:
    def __init__(self, root):
        self.root = root

        # Clock
        self.clock_utc = ttk.Label(self.root, width=8)
        # self.clock_utc.grid(row=0, column=0, sticky='e')
        self.clock_utc.pack(side='top', anchor='ne')

        self.tab_controler = ttk.Notebook(root)
        self.tab_jumps = ttk.Frame(self.tab_controler)
        self.tab_finance = ttk.Frame(self.tab_controler)

        self.tab_controler.add(self.tab_jumps, text='Jumps')
        self.tab_controler.add(self.tab_finance, text='Finance')

        # Make the grid expand when the window is resized
        self.tab_jumps.rowconfigure(0, pad=1, weight=1)
        self.tab_jumps.columnconfigure(0, pad=1, weight=1)
        self.tab_finance.rowconfigure(0, pad=1, weight=1)
        self.tab_finance.columnconfigure(0, pad=1, weight=1)

        self.tab_controler.pack(expand=True, fill='both')
        # self.tab_controler.grid(row=1, column=0, sticky='nsew')

        # Initialize the tksheet.Sheet widget
        self.sheet = Sheet(self.tab_jumps)
        self.sheet.grid(row=0, column=0, columnspan=3, sticky='nswe')
        self.sheet.change_theme('dark', redraw=False)

        # Set column headers
        self.sheet.headers([
            'Carrier Name', 'Carrier ID', 'Current System', 'Body',
            'Status', 'Destination System', 'Body', 'Timer'
        ])

        # Enable column resizing to match window resizing
        self.sheet.enable_bindings('all')
        self.sheet.column_width_resize_enabled = False
        self.sheet.row_height_resize_enabled = False
        
        self.bottom_bar = ttk.Frame(self.tab_jumps)
        self.bottom_bar.grid(row=1, column=0, columnspan=3, sticky='ew')
        self.tab_jumps.grid_rowconfigure(1, weight=0)
        # Buttons
        # Post trade
        self.button_post_trade = ttk.Button(self.bottom_bar, text='Post Trade')
        # self.button_post_trade.grid(row=0, column=0, sticky='sw')
        self.button_post_trade.pack(side='left')
        # Hammertime
        self.button_get_hammer = ttk.Button(self.bottom_bar, text='Get Hammer Time')
        # self.button_get_hammer.grid(row=0, column=1, sticky='s')
        self.button_get_hammer.pack(side='left')
        # Manual timer
        self.button_manual_timer = ttk.Button(self.bottom_bar, text='Enter Swap TImer')
        self.button_manual_timer.pack(side='left')
        # Departure notice
        self.button_post_departure = ttk.Button(self.bottom_bar, text='Post Departure')
        self.button_post_departure.pack(side='left')

        # finance tab
        self.sheet_finance = Sheet(self.tab_finance)
        self.sheet_finance.grid(row=0, column=0, columnspan=3, sticky='nswe')
        self.sheet_finance.change_theme('dark', redraw=False)

        # Set column headers
        self.sheet_finance.headers([
            'Carrier Name', 'Carrier Balance', 'CMDR Balance', 'Total', 'Reserve Balance', 'Available Balance',
        ])
        self.sheet_finance['B:G'].align('right')

        # Enable column resizing to match window resizing
        self.sheet_finance.enable_bindings('all')
        self.sheet_finance.column_width_resize_enabled = False
        self.sheet_finance.row_height_resize_enabled = False


    def update_table(self, data):
        self.sheet.set_sheet_data(data, reset_col_positions=False)
        self.sheet.set_all_cell_sizes_to_text()
    
    def update_time(self, time:str):
        self.clock_utc.configure(text=time)
    
    def update_table_finance(self, data):
        self.sheet_finance.set_sheet_data(data, reset_col_positions=False)
        self.sheet_finance.set_all_cell_sizes_to_text()

    def show_message_box_info(self, title:str, message:str):
        self.root.attributes('-topmost', True)
        messagebox.showinfo(title=title, message=message)
        self.root.attributes('-topmost', False)

    def show_message_box_warning(self, title:str, message:str):
        self.root.attributes('-topmost', True)
        messagebox.showwarning(title=title, message=message)
        self.root.attributes('-topmost', False)

class TradePostView:
    def __init__(self, root, carrier_name:str, trade_type:Literal['loading', 'unloading'], commodity:str, stations:list[str], pad_sizes:list[Literal['L', 'M']], system:str, amount:int|float):
        self.pad_sizes = pad_sizes
        
        self.popup = tk.Toplevel(root)
        self.popup.rowconfigure(1, pad=1, weight=1)
        self.popup.columnconfigure(0, pad=1, weight=1)
        
        self.label_carrier_name = ttk.Label(self.popup, text=carrier_name)
        self.label_carrier_name.grid(row=0, column=0, padx=2)
        self.label_is = ttk.Label(self.popup, text='is')
        self.label_is.grid(row=0, column=1, padx=2)
        self.label_trade_type = ttk.Label(self.popup, text=trade_type)
        self.label_trade_type.grid(row=0, column=2, padx=2)
        self.label_commodity = ttk.Label(self.popup, text=commodity)
        self.label_commodity.grid(row=0, column=3, padx=2)
        self.label_from_to = ttk.Label(self.popup, text='from' if trade_type=='loading' else 'to')
        self.label_from_to.grid(row=0, column=4, padx=2)
        self.cbox_stations = ttk.Combobox(self.popup, values=stations)
        self.cbox_stations.current(0)
        self.cbox_stations.bind('<<ComboboxSelected>>', self.station_selected)
        self.cbox_stations.grid(row=0, column=5, padx=2)
        self.cbox_pad_size = ttk.Combobox(self.popup, values=['L', 'M'], state='readonly', width=2)
        self.cbox_pad_size.set(pad_sizes[0])
        self.cbox_pad_size.grid(row=0, column=6, padx=2)
        self.label_pad_size_desp = ttk.Label(self.popup, text='Pads')
        self.label_pad_size_desp.grid(row=0, column=7, padx=2)
        self.label_in = ttk.Label(self.popup, text='in')
        self.label_in.grid(row=0, column=8, padx=2)
        self.label_system = ttk.Label(self.popup, text=system)
        self.label_system.grid(row=0, column=9, padx=2)
        self.cbox_profit = ttk.Combobox(self.popup, values=[i for i in range(10, 21)], width=5)
        self.cbox_profit.current(0)
        self.cbox_profit.grid(row=0, column=10, padx=2)
        self.label_k_per_ton = ttk.Label(self.popup, text='k/unit profit')
        self.label_k_per_ton.grid(row=0, column=11, padx=2)
        self.label_amount = ttk.Label(self.popup, text=amount)
        self.label_amount.grid(row=0, column=12, padx=2)
        self.label_units = ttk.Label(self.popup, text='k units')
        self.label_units.grid(row=0, column=13, padx=2)
        self.button_post = ttk.Button(self.popup, text='OK')
        self.button_post.grid(row=1, column=0, columnspan=14, pady=10)
    
    def station_selected(self, event):
        self.cbox_pad_size.current(0 if self.pad_sizes[self.cbox_stations.current()] == 'L' else 1)

class ManualTimerView:
    def __init__(self, root):
        self.popup = tk.Toplevel(root)
        self.popup.geometry(WINDOW_SIZE_TIMER)
        self.popup.focus_force()
        self.popup.rowconfigure(1, pad=1, weight=1)
        self.popup.columnconfigure(0, pad=1, weight=1)

        self.label_timer_desp = ttk.Label(self.popup, text='Enter timer:')
        self.label_timer_desp.pack(side='top')
        self.entry_timer = ttk.Entry(self.popup)
        self.entry_timer.pack(side='top')
        self.button_post = ttk.Button(self.popup, text='OK')
        self.button_post.pack(side='bottom')

