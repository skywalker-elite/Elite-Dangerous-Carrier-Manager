import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
from tksheet import Sheet
from typing import Literal
from config import WINDOW_SIZE_TIMER, font_sizes
import tkinter.font as tkfont
from station_parser import getStockPrice

class CarrierView:
    def __init__(self, root:tk.Tk):
        self.root = root

        # TopBar
        self.top_bar = ttk.Frame(self.root)
        self.top_bar.pack(side='top', fill='x')
        
        # Clock
        self.clock_utc = ttk.Label(self.top_bar, width=8)
        self.clock_utc.pack(side='right', anchor='ne')

        # Version
        self.label_version = ttk.Label(self.top_bar)
        self.label_version.pack(side='left', anchor='nw', padx=10)

        self.tab_controler = ttk.Notebook(root)
        self.tab_jumps = ttk.Frame(self.tab_controler)
        self.tab_finance = ttk.Frame(self.tab_controler)
        self.tab_trade = ttk.Frame(self.tab_controler)
        self.tab_services = ttk.Frame(self.tab_controler)
        self.tab_misc = ttk.Frame(self.tab_controler)
        self.tab_options = ScrollableFrame(self.tab_controler)

        self.tab_controler.add(self.tab_jumps, text='Jumps')
        self.tab_controler.add(self.tab_trade, text='Trade')
        self.tab_controler.add(self.tab_finance, text='Finance')
        self.tab_controler.add(self.tab_services, text='Services')
        self.tab_controler.add(self.tab_misc, text='Misc')
        self.tab_controler.add(self.tab_options, text='Options')

        # Make the grid expand when the window is resized
        self.tab_jumps.rowconfigure(0, pad=1, weight=1)
        self.tab_jumps.columnconfigure(0, pad=1, weight=1)
        self.tab_trade.rowconfigure(0, pad=1, weight=1)
        self.tab_trade.columnconfigure(0, pad=1, weight=1)
        self.tab_finance.rowconfigure(0, pad=1, weight=1)
        self.tab_finance.columnconfigure(0, pad=1, weight=1)
        self.tab_services.rowconfigure(0, pad=1, weight=1)
        self.tab_services.columnconfigure(0, pad=1, weight=1)
        self.tab_misc.rowconfigure(0, pad=1, weight=1)
        self.tab_misc.columnconfigure(0, pad=1, weight=1)

        self.tab_controler.pack(expand=True, fill='both')

        # Initialize the tksheet.Sheet widget
        self.sheet_jumps = Sheet(self.tab_jumps, name='sheet_jumps')
        self.sheet_jumps.grid(row=0, column=0, columnspan=3, sticky='nswe')
        self.sheet_jumps.change_theme('dark', redraw=False)

        # Set column headers
        self.sheet_jumps.headers([
            'Carrier Name', 'Carrier ID', 'Fuel', 'Current System', 'Body',
            'Status', 'Destination System', 'Body', 'Timer', 'Swap Timer',
        ])

        # Enable column resizing to match window resizing
        self.sheet_jumps.enable_bindings('single_select', 'drag_select', 'column_select', 'row_select', 'arrowkeys', 'copy', 'find', 'ctrl_click_select', 'right_click_popup_menu', 'rc_select')
        self.sheet_jumps.column_width_resize_enabled = False
        self.sheet_jumps.row_height_resize_enabled = False
        
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
        self.button_manual_timer = ttk.Button(self.bottom_bar, text='Enter Swap Timer')
        self.button_manual_timer.pack(side='left')
        # Clear timer
        self.button_clear_timer = ttk.Button(self.bottom_bar, text='Clear Timer')
        self.button_clear_timer.pack(side='left')
        # Departure notice
        self.button_post_departure = ttk.Button(self.bottom_bar, text='Post Departure')
        self.button_post_departure.pack(side='left')

        # Trade tab
        self.sheet_trade = Sheet(self.tab_trade, name='sheet_trade')
        self.sheet_trade.grid(row=0, column=0, columnspan=3, sticky='nswe')
        self.sheet_trade.change_theme('dark', redraw=False)

        # Set column headers
        self.sheet_trade.headers([
            'Carrier Name', 'Trade Type', 'Amount', 'Commodity', 'Price', 'Time Set (local)'
        ])
        self.sheet_trade['C'].align('right')
        self.sheet_trade['E'].align('right')
        
        # Enable column resizing to match window resizing
        self.sheet_trade.enable_bindings('single_select', 'drag_select', 'column_select', 'row_select', 'arrowkeys', 'copy', 'find', 'ctrl_click_select', 'right_click_popup_menu', 'rc_select')
        self.sheet_trade.column_width_resize_enabled = False
        self.sheet_trade.row_height_resize_enabled = False

        self.bottom_bar_trade = ttk.Frame(self.tab_trade)
        self.bottom_bar_trade.grid(row=1, column=0, columnspan=3, sticky='ew')
        self.tab_trade.grid_rowconfigure(1, weight=0)
        # Buttons
        # Post trade
        self.button_post_trade_trade = ttk.Button(self.bottom_bar_trade, text='Post Trade')
        # self.button_post_trade.grid(row=0, column=0, sticky='sw')
        self.button_post_trade_trade.pack(side='left')

        # finance tab
        self.sheet_finance = Sheet(self.tab_finance, name='sheet_finance')
        self.sheet_finance.grid(row=0, column=0, columnspan=3, sticky='nswe')
        self.sheet_finance.change_theme('dark', redraw=False)

        # Set column headers
        self.sheet_finance.headers([
            'Carrier Name', 'CMDR Name', 'Carrier Balance', 'CMDR Balance', 'Total', 'Services Upkeep', 'Est. Jump Cost', 'Funded Till'
        ])
        self.sheet_finance['C:K'].align('right')

        # Enable column resizing to match window resizing
        self.sheet_finance.enable_bindings('single_select', 'drag_select', 'column_select', 'row_select', 'arrowkeys', 'copy', 'find', 'ctrl_click_select', 'right_click_popup_menu', 'rc_select')
        self.sheet_finance.column_width_resize_enabled = False
        self.sheet_finance.row_height_resize_enabled = False

        # services tab
        self.sheet_services = Sheet(self.tab_services, name='sheet_services')
        self.sheet_services.grid(row=0, column=0, columnspan=3, sticky='nswe')
        self.sheet_services.change_theme('dark', redraw=False)

        # Set column headers
        self.sheet_services.headers([
            'Carrier Name', 'Refuel', 'Repair', 'Rearm', 'Shipyard', 'Outfitting', 'Cartos', 'Genomics', 'Pioneer', 'Bar', 'Redemption', 'BlackMarket'
        ])
        self.sheet_services['B:L'].align('right')

        # Enable column resizing to match window resizing
        self.sheet_services.enable_bindings('single_select', 'drag_select', 'column_select', 'row_select', 'arrowkeys', 'copy', 'find', 'ctrl_click_select', 'right_click_popup_menu', 'rc_select')
        self.sheet_services.column_width_resize_enabled = False
        self.sheet_services.row_height_resize_enabled = False

        # Misc tab
        self.sheet_misc = Sheet(self.tab_misc, name='sheet_misc')
        self.sheet_misc.grid(row=0, column=0, columnspan=3, sticky='nswe')
        self.sheet_misc.change_theme('dark', redraw=False)

        # Set column headers
        self.sheet_misc.headers([
            'Carrier Name', 'Docking', 'Notorious', 'Services', 'Cargo', 'BuyOrder', 'ShipPacks', 'ModulePacks', 'FreeSpace', 'Time Bought (Local)', 'Last Updated'
        ])
        self.sheet_misc['B:J'].align('right')

        # Enable column resizing to match window resizing
        self.sheet_misc.enable_bindings('single_select', 'drag_select', 'column_select', 'row_select', 'arrowkeys', 'copy', 'find', 'ctrl_click_select', 'right_click_popup_menu', 'rc_select')
        self.sheet_misc.column_width_resize_enabled = False
        self.sheet_misc.row_height_resize_enabled = False

        # Options tab
        self.labelframe_EDCM = ttk.Labelframe(self.tab_options.scrollable_frame, text='EDCM')
        self.labelframe_EDCM.grid(row=0, column=0, padx=10, pady=10, sticky='w')
        self.button_check_updates = ttk.Button(self.labelframe_EDCM, text='Check for Updates')
        self.button_check_updates.grid(row=0, column=0, padx=10, pady=10, sticky='w')
        self.button_go_to_github = ttk.Button(self.labelframe_EDCM, text='Go to GitHub Repo')
        self.button_go_to_github.grid(row=0, column=1, padx=10, pady=10, sticky='w')
        self.button_clear_cache = ttk.Button(self.labelframe_EDCM, text='Clear Cache and Reload')
        self.button_clear_cache.grid(row=0, column=2, padx=10, pady=10, sticky='w')

        self.labelframe_settings = ttk.Labelframe(self.tab_options.scrollable_frame, text='Settings')
        self.labelframe_settings.grid(row=1, column=0, padx=10, pady=10, sticky='w')
        self.button_reload_settings = ttk.Button(self.labelframe_settings, text='Reload Settings File')
        self.button_reload_settings.grid(row=0, column=0, padx=10, pady=10, sticky='w')
        self.button_open_settings = ttk.Button(self.labelframe_settings, text='Open Settings File')
        self.button_open_settings.grid(row=0, column=1, padx=10, pady=10, sticky='w')
        self.button_reset_settings = ttk.Button(self.labelframe_settings, text='Reset Settings to Defaults')
        self.button_reset_settings.grid(row=0, column=2, padx=10, pady=10, sticky='w')
        self.button_open_settings_dir = ttk.Button(self.labelframe_settings, text='Open Settings Directory')
        self.button_open_settings_dir.grid(row=0, column=3, padx=10, pady=10, sticky='w')

        self.labelframe_testing = ttk.Labelframe(self.tab_options.scrollable_frame, text='Testing')
        self.labelframe_testing.grid(row=2, column=0, padx=10, pady=10, sticky='w')
        self.button_test_trade_post = ttk.Button(self.labelframe_testing, text='Test Trade Post')
        self.button_test_trade_post.grid(row=0, column=0, padx=10, pady=10, sticky='w')
        self.button_test_wine_unload = ttk.Button(self.labelframe_testing, text='Test Wine Unload')
        self.button_test_wine_unload.grid(row=0, column=1, padx=10, pady=10, sticky='w')
        self.button_test_discord = ttk.Button(self.labelframe_testing, text='Test Discord Webhook')
        self.button_test_discord.grid(row=1, column=0, padx=10, pady=10, sticky='w')
        self.button_test_discord_ping = ttk.Button(self.labelframe_testing, text='Test Discord Ping')
        self.button_test_discord_ping.grid(row=1, column=1, padx=10, pady=10, sticky='w')

    def set_font_size(self, font_size:str, font_size_table:str):
        size = font_sizes.get(font_size, font_sizes['normal'])
        size_table = font_sizes.get(font_size_table, font_sizes['normal'])

        # 1) resize all tksheets
        for sheet in [self.sheet_jumps, self.sheet_trade, self.sheet_finance, self.sheet_services, self.sheet_misc]:
            sheet.font(('Calibri', size_table, 'normal'))
            sheet.header_font(('Calibri', size_table, 'normal'))

        # 2) resize all Tk widgets via named‐fonts
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            f = tkfont.nametofont(name)
            f.configure(size=size)

        # 3) resize all ttk widgets via style
        style = ttk.Style(self.root)
        # catch everything that uses the “.” fallback
        style.configure(".", font=("Calibri", size, "normal"))
        # explicitly re-configure the most common widget styles
        for cls in (
            "TButton", "TLabel", "TEntry", "TCombobox",
            "TNotebook.Tab", "TLabelframe.Label", "TLabelframe"
        ):
            style.configure(cls, font=("Calibri", size, "normal"))

        # 4) global default for any new tk/ttk widget
        self.root.option_add("*Font", ("Calibri", size, "normal"))

        # 5) some pure-tk popups (Combobox listbox, Menu) still need an option_add
        self.root.option_add("*Listbox*Font", ("Calibri", size, "normal"))
        self.root.option_add("*Menu*Font",    ("Calibri", size, "normal"))

    def update_table(self, table:Sheet, data, rows_pending_decomm:list[int]|None=None):
        table.set_sheet_data(data, reset_col_positions=False)
        table.dehighlight_all(redraw=False)
        if rows_pending_decomm is not None:
            table.highlight_rows(rows_pending_decomm, fg='red', redraw=False)
        table.set_all_column_widths()
    
    def update_table_jumps(self, data, rows_pending_decomm:list[int]|None=None):
        self.update_table(self.sheet_jumps, data, rows_pending_decomm)
    
    def update_time(self, time:str):
        self.clock_utc.configure(text=time)
    
    def update_table_finance(self, data, rows_pending_decomm:list[int]|None=None):
        self.update_table(self.sheet_finance, data, rows_pending_decomm)

    def update_table_trade(self, data, rows_pending_decomm:list[int]|None=None):
        self.update_table(self.sheet_trade, data, rows_pending_decomm)

    def update_table_services(self, data, rows_pending_decomm:list[int]|None=None):
        self.update_table(self.sheet_services, data, rows_pending_decomm)
    
    def update_table_misc(self, data, rows_pending_decomm:list[int]|None=None):
        self.update_table(self.sheet_misc, data, rows_pending_decomm)

    def show_message_box_info(self, title:str, message:str):
        self.root.attributes('-topmost', True)
        messagebox.showinfo(title=title, message=message)
        self.root.attributes('-topmost', False)

    def show_message_box_info_no_topmost(self, title:str, message:str):
        messagebox.showinfo(title=title, message=message)
    
    def show_message_box_warning(self, title:str, message:str):
        self.root.attributes('-topmost', True)
        messagebox.showwarning(title=title, message=message)
        self.root.attributes('-topmost', False)

    def show_message_box_askyesno(self, title:str, message:str) -> bool:
        self.root.attributes('-topmost', True)
        response = messagebox.askyesno(title=title, message=message)
        self.root.attributes('-topmost', False)
        return response
    
    def show_message_box_askretrycancel(self, title:str, message:str) -> bool:
        self.root.attributes('-topmost', True)
        response = messagebox.askretrycancel(title=title, message=message)
        self.root.attributes('-topmost', False)
        return response

    def show_non_blocking_info(self, title:str, message:str):
        info = tk.Toplevel(self.root)
        info.title(title)
        info.transient(self.root) # Make it appear on top of the main window
        
        label = ttk.Label(info, text=message)
        label.pack()
        
        ok_button = ttk.Button(info, text="OK", command=info.destroy)
        ok_button.pack(pady=10)

    def show_indeterminate_progress_bar(self, title:str, message:str) -> tuple[tk.Toplevel, ttk.Progressbar]:
        progress_win = tk.Toplevel(self.root)
        progress_win.title(title)
        progress_win.transient(self.root) # Make it appear on top of the main window

        label = ttk.Label(progress_win, text=message)
        label.pack(pady=10, padx=10)
        progress_win.update_idletasks()  # Ensure the window dimensions are calculated

        progress_bar = ttk.Progressbar(progress_win, mode='indeterminate', length=progress_win.winfo_width()//2)
        progress_bar.pack(pady=10, padx=10)
        progress_bar.start(20)

        return progress_win, progress_bar

class TradePostView:
    def __init__(self, root, carrier_name:str, trade_type:Literal['loading', 'unloading'], commodity:str, stations:list[str], pad_sizes:list[Literal['L', 'M']], system:str, amount:int|float, 
                 market_ids:list[str], market_updated:list[str], price:str|int):
        self.trade_type = trade_type
        self.commodity = commodity
        self.pad_sizes = pad_sizes
        self.market_ids = market_ids
        self.market_updated = market_updated
        self.price = int(price.replace(',', '')) if isinstance(price, str) else price

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
        self.cbox_profit = ttk.Combobox(self.popup, values=[f'{i}' for i in range(10, 21)], width=5)
        self.cbox_profit.current(0)
        self.cbox_profit.grid(row=0, column=10, padx=2)
        self.label_k_per_ton = ttk.Label(self.popup, text='k/unit profit')
        self.label_k_per_ton.grid(row=0, column=11, padx=2)
        self.label_amount = ttk.Label(self.popup, text=amount)
        self.label_amount.grid(row=0, column=12, padx=2)
        self.label_units = ttk.Label(self.popup, text='k units')
        self.label_units.grid(row=0, column=13, padx=2)
        self.frame_market = ttk.Frame(self.popup)
        self.frame_market.grid(row=1, column=5, columnspan=9, sticky='ew')
        self.label_price = ttk.Label(self.frame_market, text='')
        self.label_price.pack(side='left', padx=2)
        self.label_stock = ttk.Label(self.frame_market, text='')
        self.label_stock.pack(side='left', padx=2)
        self.label_market_updated = ttk.Label(self.frame_market, text='')
        self.label_market_updated.pack(side='left', padx=2)
        self.button_post = ttk.Button(self.popup, text='OK')
        self.button_post.grid(row=2, column=0, columnspan=14, pady=10)
        
        self.station_selected(None)
    
    def station_selected(self, event):
        self.cbox_pad_size.current(0 if self.pad_sizes[self.cbox_stations.current()] == 'L' else 1)
        try:
            stock, price = getStockPrice(self.trade_type, self.market_ids[self.cbox_stations.current()], commodity_name=self.commodity)
        except Exception as e:
            self.label_price.configure(text='Error fetching price')
            self.label_stock.configure(text='Error fetching stock')
            self.label_market_updated.configure(text='Error fetching market update')
            return
        self.label_price.configure(text=f'Station price {price:,} cr' if price is not None else 'Station price unknown')
        self.label_stock.configure(text=f'{"Supply" if self.trade_type == "loading" else "Demand"}' + (f' {stock:,} units' if stock is not None else ' unknown'))
        self.label_market_updated.configure(text='Last updated: ' + (self.market_updated[self.cbox_stations.current()] if self.market_updated[self.cbox_stations.current()] is not None else ' unknown'))
        if price is not None:
            profit = self.price - price if self.trade_type == 'loading' else price - self.price
            profit = int(profit / 1000)
            self.cbox_profit.set(profit)

class ManualTimerView:
    def __init__(self, root, carrierID:str):
        self.carrierID = carrierID
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

class ScrollableFrame(ttk.Frame):
    """A scrollable frame that can contain other widgets."""
    def __init__(self, container, *args, **kwargs):
        super().__init__(container, *args, **kwargs)
        self.canvas    = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame     = ttk.Frame(self.canvas)

        self.canvas.create_window((0,0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        # whenever content or viewport changes, update scrollregion & bar‐visibility
        self.scrollable_frame .bind("<Configure>", lambda e: self._update())
        self.canvas.bind("<Configure>", lambda e: self._update())

        # wheel‐scroll
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-4>", self._on_mousewheel)  # For Linux with wheel scroll up
        self.canvas.bind("<Button-5>", self._on_mousewheel)  # For Linux with wheel scroll down

        # run once after idle to hide if unnecessary
        self.after_idle(self._update)

    def _update(self):
        # 1) update scrollregion
        self.canvas.configure(scrollregion=self.canvas.bbox("all") or (0,0,0,0))

        # 2) show or hide the bar
        bbox = self.canvas.bbox("all")
        if not bbox:
            self.scrollbar.pack_forget()
            return

        content_h = bbox[3] - bbox[1]
        view_h    = self.canvas.winfo_height()
        if content_h > view_h:
            if not self.scrollbar.winfo_ismapped():
                self.scrollbar.pack(side="right", fill="y")
        else:
            self.scrollbar.pack_forget()

    def _on_mousewheel(self, e):
        delta = int(-1 * (e.delta / 120))
        # only scroll if there’s overflow
        bbox = self.canvas.bbox("all")
        if bbox and (bbox[3] - bbox[1]) > self.canvas.winfo_height():
            self.canvas.yview_scroll(delta, "units")
        return "break"

if __name__ == '__main__':
    import sv_ttk
    from config import WINDOW_SIZE
    from main import apply_theme_to_titlebar
    root = tk.Tk()
    sv_ttk.set_theme("dark")
    root.geometry(WINDOW_SIZE)
    apply_theme_to_titlebar(root)
    view = CarrierView(root)
    root.mainloop()