# A very premitive test to check if the CarrierModel can handle missing data
import pandas as pd
import tkinter as tk
import os
import sv_ttk
import sys
from datetime import datetime, timezone
from model import CarrierModel
from utility import getJournalPath, getResourcePath
from config import WINDOW_SIZE
from controller import CarrierController

def apply_theme_to_titlebar(root):
    if sys.platform == 'win32':
        import pywinstyles
        version = sys.getwindowsversion()

        if version.major == 10 and version.build >= 22000:
            # Set the title bar color to the background color on Windows 11 for better appearance
            pywinstyles.change_header_color(root, "#1c1c1c")# if sv_ttk.get_theme() == "dark" else "#fafafa")
        elif version.major == 10:
            pywinstyles.apply_style(root, "dark")# if sv_ttk.get_theme() == "dark" else "normal")

            # A hacky way to update the title bar's color on Windows 10 (it doesn't update instantly like on Windows 11)
            root.wm_attributes("-alpha", 0.99)
            root.wm_attributes("-alpha", 1)
    else:
        pass

if __name__ == '__main__':
    for _ in range(10):
        model = CarrierModel([getJournalPath()], dropout=True)
        now = datetime.now(timezone.utc)
        model.update_carriers(now)
        print(pd.DataFrame(model.get_data(now), columns=[
                'Carrier Name', 'Carrier ID', 'Fuel', 'Current System', 'Body',
                'Status', 'Destination System', 'Body', 'Timer', 'Swap Timer',
            ]))
        print(pd.DataFrame(model.get_data_finance(), columns=[
                'Carrier Name', 'CMDR Name', 'Carrier Balance', 'CMDR Balance', 'Total', 'Services Upkeep', 'Est. Jump Cost', 'Funded Till'
            ]))
        print(pd.DataFrame(model.get_data_trade()[0], columns=[
                'Carrier Name', 'Trade Type', 'Amount', 'Commodity', 'Price', 'Time Set (local)'
            ]))
        print(pd.DataFrame(model.get_data_services(), columns=[
                'Carrier Name', 'Refuel', 'Repair', 'Rearm', 'Shipyard', 'Outfitting', 'Cartos', 'Genomics', 'Pioneer', 'Bar', 'Redemption', 'BlackMarket'
            ]))
        print(pd.DataFrame(model.get_data_misc(), columns=[
                'Carrier Name', 'Squadron', 'Docking', 'Notorious', 'Services', 'Cargo', 'BuyOrder', 'ShipPacks', 'ModulePacks', 'FreeSpace', 'Time Bought (Local)', 'Last Updated'
            ]))
    print('Carrier model test complete')
    model = CarrierModel([getJournalPath()], dropout=True)
    root = tk.Tk()
    apply_theme_to_titlebar(root)
    sv_ttk.use_dark_theme()
    root.update()
    root.title("Elite Dangerous Carrier Manager")
    root.geometry(WINDOW_SIZE)
    photo = tk.PhotoImage(file = getResourcePath(os.path.join('images','EDCM.png')))
    root.wm_iconphoto(False, photo)
    root.update()
    app = CarrierController(root, model=model)
    root.mainloop()