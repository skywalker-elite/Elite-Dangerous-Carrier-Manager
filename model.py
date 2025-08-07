import pandas as pd
from os import listdir, path
import re
import json
import threading
import locale
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from humanize import naturaltime
from random import random
from typing import Callable
from utility import getHMS, getHammerCountdown, getResourcePath, getJournalPath
from config import PADLOCK, CD, CD_cancel, JUMPLOCK, ladder_systems, AVG_JUMP_CAL_WINDOW, ASSUME_DECCOM_AFTER

class JournalReader:
    def __init__(self, journal_paths:list[str], dropout:bool=False, droplist:list[str]=None):
        self.journal_paths = journal_paths
        self.journal_processed = []
        self.journal_latest = {}
        self.journal_latest_unknown_fid = {}
        self._load_games = []
        self._carrier_locations = []
        self._jump_requests = []
        self._jump_cancels = []
        self._stats = []
        self._trade_orders = []
        self._carrier_buys = []
        self._trit_deposits = []
        self._carrier_owners = {}
        self._docking_perms = []
        self._last_items_count = {item_type: len(getattr(self, f'_{item_type}')) for item_type in ['load_games', 'carrier_locations', 'jump_requests', 'jump_cancels', 'stats', 'trade_orders', 'carrier_buys', 'trit_deposits', 'docking_perms']}
        self.items = []
        self.dropout = dropout
        self.droplist = droplist
        if self.dropout == True:
            if self.droplist is None:
                print('Dropout mode active, journal data is randomly dropped')
                self.droplist = [i for i in range(10) if random() < 0.5]
                for i in self.droplist:
                    print(f'{["load_games", "carrier_locations", "jump_requests", "jump_cancels", "stats", "trade_orders", "carrier_buys", "trit_deposits", "docking_perms", "carrier_owners"][i]} was dropped')
            else:
                print('Dropout mode active, journal data is dropped')
                self.droplist = [["load_games", "carrier_locations", "jump_requests", "jump_cancels", "stats", "trade_orders", "carrier_buys", "trit_deposits", "docking_perms", "carrier_owners"].index(i) for i in self.droplist]
                for i in self.droplist:
                    print(f'{["load_games", "carrier_locations", "jump_requests", "jump_cancels", "stats", "trade_orders", "carrier_buys", "trit_deposits", "docking_perms", "carrier_owners"][i]} was dropped')

    def read_journals(self):
        latest_journal_info = {}
        for key, value in zip(self.journal_latest.keys(), self.journal_latest.values()):
            latest_journal_info[value['filename']] = {'fid': key, 'line_pos': value['line_pos'], 'is_active': value['is_active']}
        journals = []
        for journal_path in self.journal_paths:
            files = listdir(journal_path)
            r = r'^Journal\.\d{4}-\d{2}-\d{2}T\d{6}\.\d{2}\.log$'
            journal_files = sorted([i for i in files if re.fullmatch(r, i)], reverse=False)
            assert len(journal_files) > 0, f'No journal files found in {journal_path}'
            journals += [path.join(journal_path, i) for i in journal_files]
        for journal in journals:
            if journal not in self.journal_processed:
                self._read_journal(journal)
            elif journal in latest_journal_info.keys():
                if latest_journal_info[journal]['is_active']:
                    self._read_journal(journal, latest_journal_info[journal]['line_pos'], latest_journal_info[journal]['fid'])
            elif journal in self.journal_latest_unknown_fid.keys():
                self._read_journal(journal, self.journal_latest_unknown_fid[journal]['line_pos'])
        self.items = self._get_parsed_items()
        assert len(self.items[4]) > 0, 'No carrier found, if you do have a carrier, try logging in and opening the carrier management screen'
    
    def _read_journal(self, journal:str, line_pos:int|None=None, fid_last:str|None=None):
        # print(journal)
        items = []
        with open(journal, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            line_pos_new = len(lines)
            lines = lines[line_pos:]
            # if line_pos is not None:
            #     print(*lines, sep='\n')
            for i in lines:
                try:
                    items.append(json.loads(i))
                except json.decoder.JSONDecodeError as e: # ignore ill-formated entries
                    print(f'{journal} {e}')
                    continue
        
        parsed_fid, is_active = self._parse_items(items)
        if fid_last is None:
            fid = parsed_fid
        elif parsed_fid is not None and parsed_fid != fid_last:
            fid = None
        else:
            fid = fid_last
        if is_active:
            if fid is None:
                match = re.search(r'\d{4}-\d{2}-\d{2}T\d{6}', journal)
                if datetime.now() - datetime.strptime(match.group(0), '%Y-%m-%dT%H%M%S') < timedelta(hours=1): # allows one hour for fid to show up
                    self.journal_latest_unknown_fid[journal] = {'filename': journal, 'line_pos': line_pos_new, 'is_active': is_active}
                else:
                    self.journal_latest_unknown_fid.pop(journal, None)
            else:
                self.journal_latest_unknown_fid.pop(journal, None)
                self.journal_latest[fid] = {'filename': journal, 'line_pos': line_pos_new, 'is_active': is_active}
        else:
            self.journal_latest_unknown_fid.pop(journal, None)
            if fid is not None:
                self.journal_latest[fid] = {'filename': journal, 'line_pos': line_pos_new, 'is_active': is_active}
        if journal not in self.journal_processed:
            self.journal_processed.append(journal)


    def _parse_items(self, items:list) -> tuple[str|None, bool]:
        fid = None
        fid_temp = [i['FID'] for i in items if i['event'] =='Commander']
        if len(fid_temp) > 0:
            if all(i == fid_temp[0] for i in fid_temp):
                fid = fid_temp[0]
        for item in items:
            if item['event'] == 'LoadGame':
                self._load_games.append(item)
            if item['event'] == 'CarrierLocation':
                self._carrier_locations.append(item)
            if item['event'] == 'CarrierJumpRequest':
                self._jump_requests.append(item)
            if item['event'] == 'CarrierJumpCancelled':
                self._jump_cancels.append(item)
            if item['event'] == 'CarrierStats':
                self._stats.append(item)
                if fid is not None:
                    self._carrier_owners[item['CarrierID']] = fid
            if item['event'] == 'CarrierDepositFuel':
                self._trit_deposits.append(item)
            if item['event'] == 'CarrierTradeOrder':
                self._trade_orders.append(item)
            if item['event'] == 'CarrierBuy':
                self._carrier_buys.append(item)
            if item['event'] == 'CarrierDockingPermission':
                self._docking_perms.append(item)
                
        is_active = len(items) == 0 or items[-1]['event'] != 'Shutdown'
        return fid, is_active
    
    def _get_parsed_items(self):
        return [sorted(i, key=lambda x: datetime.strptime(x['timestamp'], '%Y-%m-%dT%H:%M:%SZ'), reverse=True) 
                for i in [self._load_games, self._carrier_locations, self._jump_requests, self._jump_cancels, self._stats, self._trade_orders, self._carrier_buys, self._trit_deposits, self._docking_perms]] + [self._carrier_owners]
    
    def get_items(self) -> list:
        self._last_items_count = {item_type: len(getattr(self, f'_{item_type}')) for item_type in ['load_games', 'carrier_locations', 'jump_requests', 'jump_cancels', 'stats', 'trade_orders', 'carrier_buys', 'trit_deposits', 'docking_perms']}
        if self.dropout:
            items = self.items.copy()
            for i in self.droplist:
                items[i] = type(items[i])()
            return items
        return self.items.copy()
    
    def get_new_items(self) -> list:
        items = []
        for item_type in ['load_games', 'carrier_locations', 'jump_requests', 'jump_cancels', 'stats', 'trade_orders', 'carrier_buys', 'trit_deposits', 'docking_perms']:
            items.append(getattr(self, f'_{item_type}')[self._last_items_count[item_type]:])
        self._last_items_count = {item_type: len(getattr(self, f'_{item_type}')) for item_type in ['load_games', 'carrier_locations', 'jump_requests', 'jump_cancels', 'stats', 'trade_orders', 'carrier_buys', 'trit_deposits', 'docking_perms']}
        return items + [self._carrier_owners]

class CarrierModel:
    def __init__(self, journal_paths:list[str], dropout:bool=False, droplist:list[str]=None):
        self.journal_reader = JournalReader(journal_paths, dropout=dropout, droplist=droplist)
        self.dropout = dropout
        self.droplist = droplist
        self.carriers = {}
        self.carriers_updated = {}
        self.cmdr_balances = {}
        self.cmdr_names = {}
        self.carrier_owners = {}
        self.active_timer = False
        self.manual_timers = {}
        self.journal_paths = journal_paths
        # self.read_counter = 0
        self._ignore_list = []
        self.custom_order = []
        self._callback_status_change = lambda carrierID, status_old, status_new: print(f'{self.get_name(carrierID)} status changed from {status_old} to {status_new}')
        self.df_commodities = pd.read_csv(getResourcePath(path.join('3rdParty', 'aussig.BGS-Tally', 'commodity.csv')))
        self.df_commodities['symbol'] = self.df_commodities['symbol'].str.lower()
        self.df_commodities = self.df_commodities.set_index('symbol')
        self.df_commodities_rare = pd.read_csv(getResourcePath(path.join('3rdParty', 'aussig.BGS-Tally', 'rare_commodity.csv')))
        self.df_commodities_rare['symbol'] = self.df_commodities_rare['symbol'].str.lower()
        self.df_commodities_rare = self.df_commodities_rare.set_index('symbol')
        self.df_commodities_all = pd.concat([self.df_commodities, self.df_commodities_rare])
        self.df_upkeeps = pd.DataFrame(
            {'Service': {0: 'Refuel', 1: 'Repair', 2: 'Rearm', 3: 'Shipyard', 4: 'Outfitting', 5: 'Exploration', 6: 'VistaGenomics', 7: 'PioneerSupplies', 8: 'Bartender', 9: 'VoucherRedemption', 10: 'BlackMarket'}, 'Active': {0: 1500000, 1: 1500000, 2: 1500000, 3: 6500000, 4: 5000000, 5: 1850000, 6: 1500000, 7: 5000000, 8: 1750000, 9: 1850000, 10: 2000000}, 'Paused': {0: 750000, 1: 750000, 2: 750000, 3: 1800000, 4: 1500000, 5: 700000, 6: 700000, 7: 1500000, 8: 1250000, 9: 850000, 10: 1250000}, 'Off': {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0, 8: 0, 9: 0, 10: 0}}
            ).set_index('Service')
        try:
            locale.setlocale(locale.LC_ALL, '')
        except locale.Error:
            locale.setlocale(locale.LC_ALL, 'C')
        self.read_journals()
        self.update_carriers(datetime.now(timezone.utc))

    def read_journals(self):
        self.journal_reader.read_journals()
        first_read = self.carriers == {}
        load_games, carrier_locations, jump_requests, jump_cancels, stats, trade_orders, carrier_buys, trit_deposits, docking_perms, self.carrier_owners = self.journal_reader.get_items() if first_read else self.journal_reader.get_new_items()
        # print(self.read_counter, first_read, len(load_games), len(carrier_locations), len(jump_requests), len(jump_cancels), len(stats), len(trade_orders), len(carrier_buys), len(trit_deposits), len(docking_perms))
        # self.read_counter += 1
        self.process_load_games(load_games, first_read)
        
        self.process_stats(stats, first_read)
        
        self.process_carrier_buys(carrier_buys, first_read)

        self.process_trit_deposits(trit_deposits, first_read)

        self.process_docking_perms(docking_perms, first_read)
        
        self.process_carrier_locations(carrier_locations, first_read)

        self.process_jumps(jump_requests, jump_cancels, first_read)

        self.process_trade_orders(trade_orders, first_read)

        self.fill_missing_data()

        self.update_ignore_list()

    def process_load_games(self, load_games, first_read:bool=True):
        for load_game in load_games:
            if not first_read or load_game['FID'] not in self.cmdr_balances.keys():
                self.cmdr_balances[load_game['FID']] = load_game['Credits']
            if not first_read or load_game['FID'] not in self.cmdr_names.keys():
                self.cmdr_names[load_game['FID']] = load_game['Commander']

    def process_stats(self, stats, first_read:bool=True):
        for stat in stats:
            if not first_read or stat['CarrierID'] not in self.carriers.keys():
                if stat['CarrierID'] not in self.carriers.keys():
                    self.carriers[stat['CarrierID']] = {'Callsign': stat['Callsign'], 'Name': stat['Name'], 'CMDRName': self.cmdr_names.get(self.carrier_owners.get(stat['CarrierID'], None), None)}
                else:
                    self.carriers[stat['CarrierID']]['Callsign'] = stat['Callsign']
                    self.carriers[stat['CarrierID']]['Name'] = stat['Name']
                    self.carriers[stat['CarrierID']]['CMDRName'] = self.cmdr_names.get(self.carrier_owners.get(stat['CarrierID'], None), None)
                self.carriers[stat['CarrierID']]['Finance'] = {'CarrierBalance': stat['Finance']['CarrierBalance'], 
                                                          'CmdrBalance': self.cmdr_balances[self.carrier_owners[stat['CarrierID']]] if stat['CarrierID'] in self.carrier_owners.keys() and self.carrier_owners[stat['CarrierID']] in self.cmdr_balances.keys() else None,
                                                          }
                self.carriers[stat['CarrierID']]['Fuel'] = {'FuelLevel': stat['FuelLevel'], 'JumpRange': stat['JumpRangeCurr']}
                self.carriers[stat['CarrierID']]['StatTime'] = datetime.strptime(stat['timestamp'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
                self.carriers[stat['CarrierID']]['SpaceUsage'] = {'Services': stat['SpaceUsage']['Crew'], 'Cargo': stat['SpaceUsage']['Cargo'], 'BuyOrder': stat['SpaceUsage']['CargoSpaceReserved'],
                                                             'ShipPacks': stat['SpaceUsage']['ShipPacks'], 'ModulePacks': stat['SpaceUsage']['ModulePacks'], 'FreeSpace': stat['SpaceUsage']['FreeSpace']}
                df_services = pd.DataFrame(stat['Crew'], columns=['CrewRole', 'Activated', 'Enabled']).set_index('CrewRole')
                df_services.loc[:, 'Enabled'] = df_services['Enabled'].convert_dtypes().fillna(False)
                df_services = df_services.drop(['Captain', 'CarrierFuel', 'Commodities'], axis=0, errors='ignore')
                self.carriers[stat['CarrierID']]['Services'] = df_services.copy()
                self.carriers[stat['CarrierID']]['PendingDecom'] = stat['PendingDecommission']    

    def process_carrier_buys(self, carrier_buys, first_read:bool=True):
        for carrier_buy in carrier_buys:
            if carrier_buy['CarrierID'] not in self.carriers.keys():
                self.carriers[carrier_buy['CarrierID']] = {'Callsign': carrier_buy['Callsign'], 'Name': 'Unknown', 'CMDRName': self.cmdr_names[self.carrier_owners[carrier_buy['CarrierID']]] if carrier_buy['CarrierID'] in self.carrier_owners.keys() and self.carrier_owners[carrier_buy['CarrierID']] in self.cmdr_names.keys() else None}
            if 'SpawnLocation' not in self.carriers[carrier_buy['CarrierID']].keys():
                self.carriers[carrier_buy['CarrierID']]['SpawnLocation'] = carrier_buy['Location']
            if 'TimeBought' not in self.carriers[carrier_buy['CarrierID']].keys():
                self.carriers[carrier_buy['CarrierID']]['TimeBought'] = datetime.strptime(carrier_buy['timestamp'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)    
    
    def process_trit_deposits(self, trit_deposits, first_read:bool=True):
        for trit_deposit in trit_deposits:
            if trit_deposit['CarrierID'] in self.carriers.keys():
                last_update = self.carriers[trit_deposit['CarrierID']]['StatTime'] if 'StatTime' in self.carriers[trit_deposit['CarrierID']].keys() else self.carriers[trit_deposit['CarrierID']]['Fuel']['DepotTime'] if 'Fuel' in self.carriers[trit_deposit['CarrierID']].keys() and 'DepotTime' in self.carriers[trit_deposit['CarrierID']]['Fuel'].keys() else None
                # if ('StatTime' not in self.carriers[trit_deposit['CarrierID']].keys() or datetime.strptime(trit_deposit['timestamp'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc) > self.carriers[trit_deposit['CarrierID']]['StatTime']) and ('Fuel' not in self.carriers[trit_deposit['CarrierID']].keys() or 'DepotTime' not in self.carriers[trit_deposit['CarrierID']]['Fuel'].keys()):
                if not first_read or last_update is None or datetime.strptime(trit_deposit['timestamp'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc) > last_update:
                    self.carriers[trit_deposit['CarrierID']]['Fuel'] = {'FuelLevel': trit_deposit['Total'], 'JumpRange': None, 'DepotTime': datetime.strptime(trit_deposit['timestamp'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)}
    
    def process_docking_perms(self, docking_perms, first_read:bool=True):
        for docking_perm in docking_perms:
            if docking_perm['CarrierID'] in self.carriers.keys():
                if not first_read or 'DockingPerm' not in self.carriers[docking_perm['CarrierID']].keys():
                    self.carriers[docking_perm['CarrierID']]['DockingPerm'] = {'DockingAccess': docking_perm['DockingAccess'], 'AllowNotorious': docking_perm['AllowNotorious']}

    def process_carrier_locations(self, carrier_locations, first_read:bool=True):
        for carrier_location in carrier_locations:
            if carrier_location['CarrierID'] in self.carriers.keys():
                if not first_read or 'CarrierLocation' not in self.carriers[carrier_location['CarrierID']].keys():
                    self.carriers[carrier_location['CarrierID']]['CarrierLocation'] = {'SystemName': carrier_location['StarSystem'], 'Body': None, 'BodyID': carrier_location['BodyID'], 'timestamp': datetime.strptime(carrier_location['timestamp'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)}
    
    def process_jumps(self, jump_requests, jump_cancels, first_read:bool=True):
        jumps = pd.DataFrame(jump_requests + jump_cancels, columns=['CarrierID', 'timestamp', 'event', 'SystemName', 'Body', 'BodyID', 'DepartureTime']).sort_values('timestamp', ascending=False)
        for carrierID in self.carriers.keys():
            fc_jumps = jumps[jumps['CarrierID'] == carrierID][['timestamp', 'event', 'SystemName', 'Body', 'BodyID', 'DepartureTime']].copy()
            fc_jumps['timestamp'] = fc_jumps['timestamp'].apply(lambda x: datetime.strptime(x, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc))
            last_cancel = fc_jumps[fc_jumps['event'] == 'CarrierJumpCancelled'].iloc[0] if len(fc_jumps[fc_jumps['event'] == 'CarrierJumpCancelled']) > 0 else None
            if first_read or last_cancel is not None:
                self.carriers[carrierID]['last_cancel'] = last_cancel
            if len(fc_jumps) == 0:
                if first_read or 'jumps' not in self.carriers[carrierID].keys():
                    self.carriers[carrierID]['jumps'] = pd.DataFrame(columns=['timestamp', 'event', 'SystemName', 'Body', 'BodyID', 'DepartureTime']).copy()
                    self.carriers[carrierID]['last_cancel'] = None
                continue
            cancelled = []
            flag = False
            for item in range(len(fc_jumps)):
                if fc_jumps.iloc[item]['event'] == 'CarrierJumpCancelled':
                    flag = True
                    cancelled.append(None)
                elif flag:
                    cancelled.append(True)
                    flag = False
                else:
                    cancelled.append(False)
            fc_jumps['cancelled'] = cancelled
            fc_jumps = fc_jumps[fc_jumps['cancelled'] == False].drop(['event', 'cancelled'], axis=1)
            fc_jumps_no_departure_time = fc_jumps[fc_jumps['DepartureTime'].isna()]
            assert len(fc_jumps_no_departure_time) == 0 or (fc_jumps_no_departure_time['timestamp'] < datetime(year=2022, month=12, day=1, tzinfo=timezone.utc)).all(), 'Unexpected missing jump time'
            fc_jumps_no_departure_time['DepartureTime'] = fc_jumps_no_departure_time['timestamp'] + timedelta(minutes=15)
            fc_jumps_with_departure_time = fc_jumps[fc_jumps['DepartureTime'].notna()]
            fc_jumps_with_departure_time['DepartureTime'] = fc_jumps_with_departure_time['DepartureTime'].apply(lambda x: datetime.strptime(x, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc))
            fc_jumps = pd.concat([fc_jumps_with_departure_time, fc_jumps_no_departure_time])
            fc_jumps = fc_jumps.sort_values('timestamp', ascending=False)
            if not first_read:
                old_jumps = self.carriers[carrierID]['jumps'].copy()
                if len(old_jumps) > 0:
                    if flag:
                        old_jumps.drop(0, axis=0, inplace=True)
                    if len(fc_jumps) > 0:
                        fc_jumps = pd.concat([fc_jumps, old_jumps])
                    else:
                        fc_jumps = old_jumps
            self.carriers[carrierID]['jumps'] = fc_jumps.copy()

    def process_trade_orders(self, trade_orders, first_read:bool=True):
        if len(trade_orders) != 0:
            df_trade_orders = pd.DataFrame(trade_orders, columns=['CarrierID', 'timestamp', 'event', 'Commodity', 'Commodity_Localised', 'CancelTrade', 'PurchaseOrder', 'SaleOrder', 'Price']).sort_values('timestamp', ascending=True).reset_index(drop=True).copy()
            for carrierID in self.carriers.keys():
                if 'active_trades' not in self.carriers[carrierID].keys():
                    fc_active_trades = {}
                else:
                    df_active_trades = self.carriers[carrierID]['active_trades']
                    fc_active_trades = {df_active_trades.iloc[i]['Commodity']: df_active_trades.iloc[i].to_dict() for i in range(len(df_active_trades))}
                fc_trade_orders = df_trade_orders[df_trade_orders['CarrierID'] == carrierID]
                if len(fc_trade_orders) > 0:
                    for i in range(len(fc_trade_orders)):
                        order = fc_trade_orders.iloc[i].to_dict()
                        commodity = order['Commodity']
                        if order['CancelTrade'] == True:
                            fc_active_trades.pop(commodity, None)
                        else:
                            fc_active_trades[commodity] = order
                self.carriers[carrierID]['active_trades'] = pd.DataFrame(fc_active_trades.values(), columns=['CarrierID', 'timestamp', 'event', 'Commodity', 'Commodity_Localised', 'CancelTrade', 'PurchaseOrder', 'SaleOrder', 'Price']).sort_values('timestamp', ascending=True).reset_index(drop=True).copy()
                

    def fill_missing_data(self):
        for carrierID in self.carriers.keys():
            if 'SpawnLocation' not in self.carriers[carrierID].keys():
                self.carriers[carrierID]['SpawnLocation'] = 'Unknown'

            if 'TimeBought' not in self.carriers[carrierID].keys():
                self.carriers[carrierID]['TimeBought'] = None

            if 'CarrierLocation' not in self.carriers[carrierID].keys():
                self.carriers[carrierID]['CarrierLocation'] = {'SystemName': 'Unknown', 'Body': None, 'BodyID': None, 'timestamp': None}
                
            if 'Finance' not in self.carriers[carrierID].keys():
                if self.carriers[carrierID]['TimeBought'] is not None:
                    self.carriers[carrierID]['Finance'] = {'CarrierBalance': 0, 
                                                        'CmdrBalance': self.cmdr_balances[self.carrier_owners[carrierID]] if carrierID in self.carrier_owners.keys() and self.carrier_owners[carrierID] in self.cmdr_balances.keys() else None,
                                                        }
                
            if 'Fuel' not in self.carriers[carrierID].keys():
                if self.carriers[carrierID]['TimeBought'] is not None:
                    self.carriers[carrierID]['Fuel'] = {'FuelLevel': 500, 'JumpRange': 'Unknown'}
                else:
                    self.carriers[carrierID]['Fuel'] = {'FuelLevel': 'Unknown', 'JumpRange': 'Unknown'}

            if 'Services' not in self.carriers[carrierID].keys():
                if self.carriers[carrierID]['TimeBought'] is not None:
                    self.carriers[carrierID]['Services'] = pd.DataFrame({'Activated': {'BlackMarket': False, 'Refuel': False, 'Repair': False, 'Rearm': False, 'VoucherRedemption': False, 'Exploration': False, 'Shipyard': False, 'Outfitting': False}, 'Enabled': {'BlackMarket': False, 'Refuel': False, 'Repair': True, 'Rearm': False, 'VoucherRedemption': False, 'Exploration': False, 'Shipyard': False, 'Outfitting': False}})

            if 'StatTime' not in self.carriers[carrierID].keys():
                self.carriers[carrierID]['StatTime'] = None
                
            if 'DockingPerm' not in self.carriers[carrierID].keys():
                if self.carriers[carrierID]['TimeBought'] is not None:
                    self.carriers[carrierID]['DockingPerm'] = {'DockingAccess': 'all', 'AllowNotorious': False}
                else:
                    self.carriers[carrierID]['DockingPerm'] = {'DockingAccess': None, 'AllowNotorious': None}
                
            if 'SpaceUsage' not in self.carriers[carrierID].keys():
                self.carriers[carrierID]['SpaceUsage'] = {'Services': None, 'Cargo': None, 'BuyOrder': None, 'ShipPacks': None, 'ModulePacks': None, 'FreeSpace': None}

            if 'PendingDecom' not in self.carriers[carrierID].keys():
                self.carriers[carrierID]['PendingDecom'] = False

            if 'active_trades' not in self.carriers[carrierID].keys():
                self.carriers[carrierID]['active_trades'] = pd.DataFrame({}, columns=['CarrierID', 'timestamp', 'event', 'Commodity', 'Commodity_Localised', 'CancelTrade', 'PurchaseOrder', 'SaleOrder', 'Price'])

    def update_ignore_list(self):
        for carrierID in self.get_carriers_pending_decom():
            if carrierID in self._ignore_list:
                continue
            now = datetime.now(timezone.utc)
            if self.get_stat_time(carrierID) is not None and now.astimezone() - self.get_stat_time(carrierID) > ASSUME_DECCOM_AFTER:
                self._ignore_list.append(carrierID)

    def add_ignore_list(self, call_signs:list[str]):
        for call_sign in call_signs:
            carrierID = self.get_id_by_callsign(call_sign)
            if carrierID is not None and carrierID not in self._ignore_list:
                self._ignore_list.append(carrierID)
    
    def reset_ignore_list(self):
        self._ignore_list = []
    
    def update_carriers(self, now):
        carriers = self.carriers.copy()
        for carrierID in carriers.keys():
            data = carriers[carrierID].copy()
            if len(data['jumps']) == 0:
                data['latest_depart'] = None
                latest_body = None
                latest_body_id = None
                if data['CarrierLocation']['timestamp'] is not None:
                    latest_system = data['CarrierLocation']['SystemName']
                    latest_body = data['CarrierLocation']['Body']
                    latest_body_id = data['CarrierLocation']['BodyID']
                else:
                    latest_system = data['SpawnLocation']
                time_diff = None
            else:
                data['latest_depart'] = data['jumps'].iloc[0]['DepartureTime']
                latest_body = data['jumps'].iloc[0]['Body']
                latest_body_id = data['jumps'].iloc[0]['BodyID']
                latest_system = data['jumps'].iloc[0]['SystemName']
                pre_body = data['jumps'].iloc[1]['Body'] if len(data['jumps']) > 1 else 'Unknown'
                pre_body_id = data['jumps'].iloc[1]['BodyID'] if len(data['jumps']) > 1 else 'Unknown'
                pre_system = data['jumps'].iloc[1]['SystemName'] if len(data['jumps']) > 1 else data['SpawnLocation']
                time_diff = now - data['latest_depart']
            
            if data['last_cancel'] is not None:
                time_diff_cancel = now - data['last_cancel']['timestamp']
            else:
                time_diff_cancel = None

            if time_diff is not None and time_diff < timedelta(0):
                self.active_timer = True
                data['status'] = 'jumping'
                if data['CarrierLocation']['timestamp'] is not None and (len(data['jumps']) == 1 or data['CarrierLocation']['timestamp'] > data['jumps'].iloc[1]['DepartureTime']) and data['CarrierLocation']['SystemName'] != pre_system:
                    pre_system = data['CarrierLocation']['SystemName']
                    pre_body = data['CarrierLocation']['Body']
                    pre_body_id = data['CarrierLocation']['BodyID']
                data['current_system'] = pre_system
                data['current_body'] = pre_body
                data['current_body_id'] = pre_body_id
                data['destination_system'] = latest_system
                data['destination_body'] = latest_body
                data['destination_body_id'] = latest_body_id
            elif time_diff is not None and time_diff < CD:
                self.active_timer = True
                data['status'] = 'cool_down'
                data['current_system'] = latest_system
                data['current_body'] = latest_body
                data['current_body_id'] = latest_body_id
                data['destination_system'] = None
                data['destination_body'] = None
                data['destination_body_id'] = None
            elif time_diff_cancel is not None and time_diff_cancel < CD_cancel:
                self.active_timer = True
                data['status'] = 'cool_down_cancel'
                data['current_system'] = latest_system
                data['current_body'] = latest_body
                data['current_body_id'] = latest_body_id
                data['destination_system'] = None
                data['destination_body'] = None
                data['destination_body_id'] = None
            else:
                self.active_timer = False
                data['status'] = 'idle'
                if data['CarrierLocation']['timestamp'] is not None and (data['latest_depart'] is None or data['CarrierLocation']['timestamp'] > data['latest_depart']) and data['CarrierLocation']['SystemName'] != latest_system:
                    latest_system = data['CarrierLocation']['SystemName']
                    latest_body = data['CarrierLocation']['Body']
                    latest_body_id = data['CarrierLocation']['BodyID']
                data['current_system'] = latest_system
                data['current_body'] = latest_body
                data['current_body_id'] = latest_body_id
                data['destination_system'] = None
                data['destination_body'] = None
                data['destination_body_id'] = None
            carriers[carrierID] = data
                  
        old_status = {carrierID: self.carriers_updated[carrierID]['status'] for carrierID in self.carriers_updated.keys()}
        new_status = {carrierID: carriers[carrierID]['status'] for carrierID in carriers.keys()}
        self.carriers_updated = carriers.copy()

        for carrierID in old_status.keys() & new_status.keys():
            if new_status[carrierID] != old_status[carrierID] and carrierID not in self._ignore_list:
                # print(f'model:{self.get_name(carrierID)} status changed from {old_status[carrierID]} to {new_status[carrierID]}')
                self._callback_status_change(carrierID, old_status[carrierID], new_status[carrierID])

    def register_status_change_callback(self, callback:Callable[[str, str, str], None]):
        self._callback_status_change = lambda carrierID, status_old, status_new: threading.Thread(target=callback, args=(carrierID, status_old, status_new)).start()
    
    def get_carriers(self):
        return self.carriers_updated.copy()
    
    def get_data(self, now):
        return [self.generateInfo(carrierID, now) for carrierID in self.sorted_ids_display()]

    def generateInfo(self, carrierID, now):
        carrier = self.get_carriers()[carrierID]
        location_system, location_body = getLocation(carrier['current_system'], carrier['current_body'], carrier['current_body_id'])
        fuel_level = carrier['Fuel']['FuelLevel']
        timer = self.manual_timers.get(carrierID, None)
        timer = timer['time'].strftime('%H:%M:%S') if timer is not None else ''
        if carrier['status'] == 'jumping':
            destination_system, destination_body = getLocation(carrier['destination_system'], carrier['destination_body'], carrier['destination_body_id'])
            time_diff = carrier['latest_depart'] - now
            h, m, s = getHMS(time_diff.total_seconds())
            return (
                f"{carrier['Name']}", 
                f"{carrier['Callsign']}", 
                f"{fuel_level}",
                f"{location_system}", 
                f"{location_body}", 
                f"Pad Locked" if time_diff < PADLOCK else "Jump Locked" if time_diff < JUMPLOCK else f"Jumping",
                f"{destination_system}", 
                f"{destination_body}", 
                f"{h:.0f} h {m:02.0f} m {s:02.0f} s", 
                f"{timer}"
                )
        elif carrier['status'] == 'cool_down':
            time_diff = CD - (now - carrier['latest_depart'])
            h, m, s = getHMS(time_diff.total_seconds())
            return (
                f"{carrier['Name']}", 
                f"{carrier['Callsign']}", 
                f"{fuel_level}",
                f"{location_system}", 
                f"{location_body}", 
                f"Cooling Down",
                f"", 
                f"",
                f"{h:.0f} h {m:02.0f} m {s:02.0f} s", 
                f"{timer}"
                )
        elif carrier['status'] == 'cool_down_cancel':
            time_diff = CD_cancel - (now - carrier['last_cancel']['timestamp'])
            h, m, s = getHMS(time_diff.total_seconds())
            return (
                f"{carrier['Name']}", 
                f"{carrier['Callsign']}", 
                f"{fuel_level}",
                f"{location_system}", 
                f"{location_body}", 
                f"Cooling Down",
                f"", 
                f"",
                f"{h:.0f} h {m:02.0f} m {s:02.0f} s", 
                f"{timer}"
                )
        else:
            return (
                f"{carrier['Name']}", 
                f"{carrier['Callsign']}", 
                f"{fuel_level}",
                f"{location_system}", 
                f"{location_body}", 
                f"Idle",
                f"", 
                f"",
                f"",
                f"{timer}"
                )
    
    def get_data_finance(self):
        df = pd.DataFrame([self.generate_info_finance(carrierID) for carrierID in self.sorted_ids_display()], columns=['Carrier Name', 'CMDR Name', 'Carrier Balance', 'CMDR Balance', 'Services Upkeep', 'Est. Jump Cost', 'Funded Till'])
        # handles unknown cmdr balance
        idx_no_cmdr = df[df['CMDR Balance'].isna()].index
        df.loc[idx_no_cmdr, 'CMDR Balance'] = 0
        df.insert(4, 'Total', df['Carrier Balance'].astype(int) + df['CMDR Balance'].astype(int))
        df = pd.concat([df, pd.DataFrame([['Total'] + [''] +[df.iloc[:,i].astype(int).sum() for i in range(2, 7)] + ['']], columns=df.columns)], axis=0, ignore_index=True)
        df = df.astype('object') # to comply with https://pandas.pydata.org/docs/dev/whatsnew/v2.1.0.html#deprecated-silent-upcasting-in-setitem-like-series-operations
        df.iloc[:, 2:] = df.iloc[:, 2:].apply(lambda x: [f'{int(xi):,}' if type(xi) == int else xi for xi in x])
        df.loc[idx_no_cmdr, 'CMDR Balance'] = 'Unknown'
        return df.values.tolist()
    
    def generate_info_finance(self, carrierID):
        finance = [n for n in self.get_finance(carrierID).values()]
        upkeep = self.calculate_upkeep(carrierID=carrierID)
        jump_cost = self.calculate_average_jump_costs(carrierID=carrierID)
        afloat_time = self.calculate_afloat_time(carrierID=carrierID, carrier_balance=finance[0], upkeep=upkeep, jump_cost=jump_cost)
        return (self.get_name(carrierID=carrierID), self.generate_info_cmdr_name(carrierID), *finance, upkeep, jump_cost, afloat_time)
    
    def get_finance(self, carrierID):
        return self.get_carriers()[carrierID]['Finance']
    
    def generate_info_cmdr_name(self, carrierID) -> str:
        cmdr_name = self.get_cmdr_name(carrierID=carrierID)
        return cmdr_name if cmdr_name is not None else 'Unknown'
    
    def get_cmdr_name(self, carrierID) -> str|None:
        return self.get_carriers()[carrierID]['CMDRName']

    def calculate_afloat_time(self, carrierID, carrier_balance:int, upkeep:int, jump_cost:int) -> str:
        stat_time = self.get_stat_time(carrierID=carrierID)
        stat_time = stat_time if stat_time is not None else datetime.now().astimezone()
        return naturaltime(stat_time + timedelta(weeks=carrier_balance / (upkeep+jump_cost)))
    
    def calculate_upkeep(self, carrierID) -> int:
        df = self.generate_info_services(carrierID=carrierID)
        result = 5000000
        for i in df.index:
            result += self.df_upkeeps.loc[i, df.loc[i]]
        return result
    
    def calculate_average_jump_costs(self, carrierID) -> int:
        df = self.get_carriers()[carrierID]['jumps']
        df = df[datetime.now().astimezone() - df['timestamp'] < timedelta(weeks=AVG_JUMP_CAL_WINDOW)]
        return int(round(len(df) / AVG_JUMP_CAL_WINDOW, 2) * 100000)
    
    def get_data_services(self):
        df = pd.DataFrame([self.generate_info_services(carrierID) for carrierID in self.sorted_ids_display()], columns=['Refuel', 'Repair', 'Rearm', 'Shipyard', 'Outfitting', 'Exploration', 'VistaGenomics', 'PioneerSupplies', 'Bartender', 'VoucherRedemption', 'BlackMarket'])
        df[['VistaGenomics', 'PioneerSupplies', 'Bartender']] = df[['VistaGenomics', 'PioneerSupplies', 'Bartender']].fillna('Off')
        df['Carrier Name'] = [self.get_name(carrierID) for carrierID in self.sorted_ids_display()]
        return df[['Carrier Name', 'Refuel', 'Repair', 'Rearm', 'Shipyard', 'Outfitting', 'Exploration', 'VistaGenomics', 'PioneerSupplies', 'Bartender', 'VoucherRedemption', 'BlackMarket']].values.tolist()
    
    def generate_info_services(self, carrierID) -> pd.Series:
        df = self.get_services(carrierID=carrierID)
        status = []
        for i in range(len(df)):
            if df.iloc[i]['Activated'] == False:
                status.append('Off')
            elif df.iloc[i]['Enabled'] == False:
                status.append('Paused')
            else:
                status.append('Active')
        df['Status'] = status
        return df['Status'].T
    
    def get_services(self, carrierID):
        return self.get_carriers()[carrierID]['Services']
    
    def get_data_misc(self):
        df = pd.DataFrame()
        df['Carrier Name'] = [self.get_name(carrierID) for carrierID in self.sorted_ids_display()]
        df['Docking Permission'] = [self.generate_info_docking_perm(carrierID)[0] for carrierID in self.sorted_ids_display()]
        df['Allow Notorious'] = [self.generate_info_docking_perm(carrierID)[1] for carrierID in self.sorted_ids_display()]
        df['Services'] = [self.generate_info_space_usage(carrierID)[0] for carrierID in self.sorted_ids_display()]
        df['Cargo'] = [self.generate_info_space_usage(carrierID)[1] for carrierID in self.sorted_ids_display()]
        df['BuyOrder'] = [self.generate_info_space_usage(carrierID)[2] for carrierID in self.sorted_ids_display()]
        df['ShipPacks'] = [self.generate_info_space_usage(carrierID)[3] for carrierID in self.sorted_ids_display()]
        df['ModulePacks'] = [self.generate_info_space_usage(carrierID)[4] for carrierID in self.sorted_ids_display()]
        df['FreeSpace'] = [self.generate_info_space_usage(carrierID)[5] for carrierID in self.sorted_ids_display()]
        df['Time Bought'] = [self.generate_info_time_bought(carrierID=carrierID) for carrierID in self.sorted_ids_display()]
        df['Last Updated'] = [self.generate_info_stat_time(carrierID=carrierID) for carrierID in self.sorted_ids_display()]
        return df[['Carrier Name', 'Docking Permission', 'Allow Notorious', 'Services', 'Cargo', 'BuyOrder', 'ShipPacks', 'ModulePacks', 'FreeSpace', 'Time Bought', 'Last Updated']].values.tolist()
    
    def generate_info_docking_perm(self, carrierID):
        docking_perm = self.get_docking_perm(carrierID=carrierID)
        match docking_perm['DockingAccess']:
            case 'all':
                docking = 'All'
            case 'friends':
                docking = 'Friends'
            case 'squadron':
                docking = 'Squadron'
            case 'squadronfriends':
                docking = 'Squadron&Friends'
            case 'none':
                docking = 'None'
            case _:
                docking = 'Unknown'
        notorious = 'Yes' if docking_perm['AllowNotorious'] else 'No' if docking_perm['AllowNotorious'] is not None else 'Unknown'
        return (docking, notorious)
    
    def get_docking_perm(self, carrierID):
        return self.get_carriers()[carrierID]['DockingPerm']
    
    def generate_info_space_usage(self, carrierID):
        space_usage = self.get_space_usage(carrierID=carrierID)
        return (f"{int(space_usage['Services'])}t", f"{int(space_usage['Cargo'])}t", f"{int(space_usage['BuyOrder'])}t", f"{int(space_usage['ShipPacks'])}t", f"{int(space_usage['ModulePacks'])}t", 
                f"{int(space_usage['FreeSpace'])}t") if space_usage['Services'] is not None else ('Unknown', 'Unknown', 'Unknown', 'Unknown', 'Unknown', 'Unknown')
    
    def get_space_usage(self, carrierID):
        return self.get_carriers()[carrierID]['SpaceUsage']
    
    def generate_info_stat_time(self, carrierID) -> str:
        stat_time = self.get_stat_time(carrierID=carrierID)
        return naturaltime(stat_time) if stat_time is not None else 'Never'
    
    def get_stat_time(self, carrierID) -> datetime|None:
        return self.get_carriers()[carrierID]['StatTime']
    
    def generate_info_time_bought(self, carrierID):
        time_bought = self.get_time_bought(carrierID=carrierID)
        return time_bought.astimezone().strftime('%x %X') if time_bought is not None else 'Unknown'
    
    def get_time_bought(self, carrierID) -> datetime|None:
        return self.get_carriers()[carrierID]['TimeBought']
    
    def get_carriers_pending_decom(self) -> list[str]:
        return [carrierID for carrierID in self.sorted_ids() if self.get_pending_decom(carrierID)]
    
    def get_rows_pending_decom(self) -> list[int]|None:
        decomming = [i for i, carrierID in enumerate(self.sorted_ids_display()) if self.get_pending_decom(carrierID)]
        return decomming if len(decomming) > 0 else None
    
    def get_pending_decom(self, carrierID) -> bool:
        return self.get_carriers()[carrierID]['PendingDecom']
    
    def get_name(self, carrierID) -> str:
        return self.get_carriers()[carrierID]['Name']
    
    def get_callsign(self, carrierID) -> str:
        return self.get_carriers()[carrierID]['Callsign']
    
    def get_status(self, carrierID) -> str:
        return self.get_carriers()[carrierID]['status']

    def get_current_system(self, carrierID, use_custom_name:bool=False) -> str:
        system_name = self.get_carriers()[carrierID]['current_system']
        return get_custom_system_name(system_name) if use_custom_name else system_name

    def get_destination_system(self, carrier_ID, use_custom_name:bool=False) -> str|None:
        system_name = self.get_carriers()[carrier_ID]['destination_system']
        return get_custom_system_name(system_name) if use_custom_name else system_name

    def get_current_or_destination_system(self, carrierID, use_custom_name:bool=False) -> str:
        return self.get_destination_system(carrier_ID=carrierID, use_custom_name=use_custom_name) if self.get_status(carrierID=carrierID) == 'jumping' else self.get_current_system(carrierID=carrierID, use_custom_name=use_custom_name)

    def get_current_body(self, carrierID) -> str:
        _, body = getLocation(self.get_carriers()[carrierID]['current_system'], self.get_carriers()[carrierID]['current_body'], self.get_carriers()[carrierID]['current_body_id'])
        return body
    
    def get_destination_body(self, carrierID) -> str|None:
        _, body = getLocation(self.get_carriers()[carrierID]['destination_system'], self.get_carriers()[carrierID]['destination_body'], self.get_carriers()[carrierID]['destination_body_id'])
        return body
    
    def get_current_or_destination_body(self, carrierID) -> str:
        return self.get_destination_body(carrierID=carrierID) if self.get_status(carrierID=carrierID) == 'jumping' else self.get_current_body(carrierID=carrierID)
    
    def get_current_body_id(self, carrierID) -> int:
        return self.get_carriers()[carrierID]['current_body_id']
    
    def get_destination_body_id(self, carrierID) -> int|None:
        return self.get_carriers()[carrierID]['destination_body_id']
    
    def get_current_or_destination_body_id(self, carrierID) -> int:
        return self.get_destination_body_id(carrierID=carrierID) if self.get_status(carrierID=carrierID) == 'jumping' else self.get_current_body_id(carrierID=carrierID)
    
    def get_id_by_callsign(self, callsign) -> str|None:
        for carrierID in self.get_carriers().keys():
            if self.get_callsign(carrierID) == callsign:
                return carrierID
        return None
    
    def sorted_ids(self):
        ids = self.get_carriers().keys()
        custom_order_lookup = {callsign: idx for idx, callsign in enumerate(self.custom_order)}
        custom_ordered_ids = sorted(
            [carrierID for carrierID in ids if self.get_callsign(carrierID) in custom_order_lookup],
            key=lambda x: custom_order_lookup[self.get_callsign(x)]
        )
        remaining_ids = [carrierID for carrierID in ids if carrierID not in custom_ordered_ids]
        return custom_ordered_ids + sorted(remaining_ids, key=lambda x: self.get_time_bought(x) if self.get_time_bought(x) is not None else datetime(year=2020, month=6, day=9).replace(tzinfo=timezone.utc), reverse=False) # Assumes carrier bought at release if no buy event found

    def sorted_ids_display(self):
        return [i for i in self.sorted_ids() if i not in self._ignore_list]
    
    def get_departure_hammer_countdown(self, carrierID) -> str|None:
        latest_depart = self.get_carriers()[carrierID]['latest_depart']
        return getHammerCountdown(latest_depart.to_datetime64()) if latest_depart is not None else None
    
    def get_formated_largest_order(self, carrierID) -> str|None:
        df_active_trades = self.generate_info_trade(carrierID=carrierID)
        if len(df_active_trades) == 0:
            return None
        else:
            df_active_trades['Amount'] = df_active_trades['Amount'].str.replace(',', '').astype(float)
            df_active_trades['Time Set (Local)'] = df_active_trades['Time Set (Local)'].apply(lambda x: datetime.strptime(x, '%x %X').replace(tzinfo=timezone.utc).astimezone())
            df_active_trades.sort_values('Time Set (Local)', ascending=False, inplace=True)
            total_tonnage = 0
            for i in range(len(df_active_trades)):
                total_tonnage += df_active_trades.iloc[i]['Amount']
                if total_tonnage >= 25000:
                    df_active_trades = df_active_trades.iloc[:i]
                    break
            df_active_trades.sort_values('Amount', ascending=False, inplace=True)
            largest_order = df_active_trades.iloc[0]
            commodity = largest_order['Commodity']
            amount = largest_order['Amount']
            amount = round(amount / 500) * 500 / 1000
            if amount % 1 == 0:
                amount = int(amount)
            price = largest_order['Price']
            order_type = largest_order['Trade Type'].lower()
            return (order_type, commodity, amount, price)

    def get_data_trade(self) -> tuple[pd.DataFrame, list[int]|None]:
        trades = [self.generate_info_trade(carrierID) for carrierID in self.sorted_ids_display()]
        df = pd.concat(trades, axis=0, ignore_index=True) if len(trades) > 0 else pd.DataFrame(columns=['CarrierID', 'Carrier Name', 'Trade Type', 'Amount', 'Commodity', 'Price', 'Time Set (Local)', 'Pending Decom'])
        self.trade_carrierIDs = df['CarrierID']
        trades = df.drop(['Pending Decom', 'CarrierID'], axis=1, errors='ignore')
        pending_decom = [i for i, decomming in enumerate(df['Pending Decom']) if decomming == True]
        return trades.values.tolist(), pending_decom if len(pending_decom) > 0 else None
    
    def generate_info_trade(self, carrierID) -> pd.DataFrame:
        carrier_name = self.get_name(carrierID)
        active_trades = self.get_active_trades(carrierID)
        if len(active_trades) == 0:
            return pd.DataFrame({}, columns=['CarrierID', 'Carrier Name', 'Trade Type', 'Amount', 'Commodity', 'Price', 'Time Set (Local)', 'Pending Decom'])
        else:
            active_trades['CarrierID'] = carrierID
            active_trades['Carrier Name'] = carrier_name
            active_trades['Commodity'] = active_trades['Commodity'].apply(lambda x: self.df_commodities_all.loc[x]['name'] if x in self.df_commodities_all.index else None)
            active_trades = active_trades[active_trades['Commodity'].notna()]
            active_trades['Trade Type'] = active_trades.apply(lambda x: 'Loading' if x['PurchaseOrder'] > 0 else 'Unloading', axis=1)
            active_trades['Amount'] = active_trades.apply(lambda x: x['PurchaseOrder'] if x['PurchaseOrder'] > 0 else x['SaleOrder'], axis=1).apply(lambda x: f'{int(x):,}')
            active_trades['Price'] = active_trades['Price'].apply(lambda x: f'{int(x):,}')
            active_trades['Time Set (Local)'] = active_trades['timestamp'].apply(lambda x: datetime.strptime(x, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).astimezone().strftime('%x %X'))
            active_trades['Pending Decom'] = self.get_pending_decom(carrierID=carrierID)
            return active_trades[['CarrierID', 'Carrier Name', 'Trade Type', 'Amount', 'Commodity', 'Price', 'Time Set (Local)', 'Pending Decom']]
    
    def get_active_trades(self, carrierID) -> pd.DataFrame:
        return self.get_carriers()[carrierID]['active_trades'].copy()

def getLocation(system, body, body_id):
    if system == 'HIP 58832':
        result_system, result_body = system, {0: 'Star', 1: '1', 2: '2', 3: '3', 4: '4', 5: '5', 16: '6'}.get(body_id, 'Unknown') # Yes, the body_id of Planet 6 is 16, don't ask me why
    elif body is None or isinstance(body, float):
        if body_id == 0:
            result_system, result_body = system, 'Star'
        else:
            result_system, result_body = system, 'Unknown'
    elif system == body:
        if body_id == 0:
            result_system, result_body = body, 'Star'
        else:
            result_system, result_body = system, body
    else:
        if isinstance(body, str) and system in body:
            result_system, result_body = system, body.replace(f'{system} ', '')
        else: 
            result_system, result_body = system, body
    
    result_system = get_custom_system_name(result_system)
    return result_system, result_body

def get_custom_system_name(system_name):
    if system_name in ladder_systems.keys():
        system_name = f'{ladder_systems[system_name]} ({system_name})'
    return system_name

if __name__ == '__main__':
    model = CarrierModel(getJournalPath())
    now = datetime.now(timezone.utc)
    model.update_carriers(now)
    print(pd.DataFrame(model.get_data(now), columns=[
            'Carrier Name', 'Carrier ID', 'Fuel', 'Current System', 'Body',
            'Status', 'Destination System', 'Body', 'Timer', 'Swap Timer'
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
            'Carrier Name', 'Docking', 'Notorious', 'Services', 'Cargo', 'BuyOrder', 'ShipPacks', 'ModulePacks', 'FreeSpace', 'Time Bought (Local)', 'Last Updated'
        ]))
    # print(model.df_upkeeps)