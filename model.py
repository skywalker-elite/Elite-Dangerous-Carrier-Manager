import pandas as pd
from os import listdir, path
import re
import json
from datetime import datetime, timezone, timedelta
from humanize import naturaltime
from random import random
from utility import getHMS, getHammerCountdown, getResourcePath, getJournalPath
from config import PADLOCK, CD, CD_cancel, JUMPLOCK, ladder_systems, AVG_JUMP_CAL_WINDOW

class JournalReader:
    def __init__(self, journal_path:str, dropout:bool=False):
        self.journal_path = journal_path
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
        self.items = []
        self.dropout = dropout
        if self.dropout:
            print('Dropout mode active, journal data is randomly dropped')
            self.droplist = [i for i in range(10) if random() < 0.5]
            for i in self.droplist:
                print(f'{["load_games", "carrier_locations", "jump_requests", "jump_cancels", "stats", "trade_orders", "carrier_buys", "trit_deposits", "docking_perms", "carrier_owners"][i]} was dropped')

    def read_journals(self):
        latest_journal_info = {}
        for key, value in zip(self.journal_latest.keys(), self.journal_latest.values()):
            latest_journal_info[value['filename']] = {'fid': key, 'line_pos': value['line_pos'], 'is_active': value['is_active']}
        files = listdir(self.journal_path)
        r = r'^Journal\.\d{4}-\d{2}-\d{2}T\d{6}\.\d{2}\.log$'
        journals = sorted([i for i in files if re.fullmatch(r, i)], reverse=False)
        assert len(journals) > 0, f'No journal files found in {self.journal_path}'
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
        with open(path.join(self.journal_path, journal), 'r', encoding='utf-8') as f:
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


    def _parse_items(self, items:list) -> tuple[str, bool]:
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
        if self.dropout:
            items = self.items.copy()
            for i in self.droplist:
                items[i] = type(items[i])()
            return items
        return self.items.copy()

class CarrierModel:
    def __init__(self, journal_path:str, dropout:bool=False):
        self.journal_reader = JournalReader(journal_path, dropout=dropout)
        self.dropout = dropout
        self.carriers = {}
        self.carriers_updated = {}
        self.active_timer = False
        self.manual_timers = []
        self.journal_path = journal_path
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
        self.read_journals()

    def read_journals(self):
        self.journal_reader.read_journals()
        load_games, carrier_locations, jump_requests, jump_cancels, stats, trade_orders, carrier_buys, trit_deposits, docking_perms, carrier_owners = self.journal_reader.get_items()

        cmdr_balances = {}
        cmdr_names = {}
        for load_game in load_games:
            if load_game['FID'] not in cmdr_balances.keys():
                cmdr_balances[load_game['FID']] = load_game['Credits']
            if load_game['FID'] not in cmdr_names.keys():
                cmdr_names[load_game['FID']] = load_game['Commander']
        
        carriers = {}
        for stat in stats:
            if stat['CarrierID'] not in carriers.keys():
                carriers[stat['CarrierID']] = {'Callsign': stat['Callsign'], 'Name': stat['Name'], 'CMDRName': cmdr_names[carrier_owners[stat['CarrierID']]] if stat['CarrierID'] in carrier_owners.keys() and carrier_owners[stat['CarrierID']] in cmdr_names.keys() else None}
                carriers[stat['CarrierID']]['Finance'] = {'CarrierBalance': stat['Finance']['CarrierBalance'], 
                                                          'CmdrBalance': cmdr_balances[carrier_owners[stat['CarrierID']]] if stat['CarrierID'] in carrier_owners.keys() and carrier_owners[stat['CarrierID']] in cmdr_balances.keys() else None,
                                                          }
                carriers[stat['CarrierID']]['Fuel'] = {'FuelLevel': stat['FuelLevel'], 'JumpRange': stat['JumpRangeCurr']}
                carriers[stat['CarrierID']]['StatTime'] = datetime.strptime(stat['timestamp'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
                carriers[stat['CarrierID']]['SpaceUsage'] = {'Services': stat['SpaceUsage']['Crew'], 'Cargo': stat['SpaceUsage']['Cargo'], 'BuyOrder': stat['SpaceUsage']['CargoSpaceReserved'],
                                                             'ShipPacks': stat['SpaceUsage']['ShipPacks'], 'ModulePacks': stat['SpaceUsage']['ModulePacks'], 'FreeSpace': stat['SpaceUsage']['FreeSpace']}
                df_services = pd.DataFrame(stat['Crew'], columns=['CrewRole', 'Activated', 'Enabled']).set_index('CrewRole')
                df_services.loc[:, 'Enabled'] = df_services['Enabled'].convert_dtypes().fillna(False)
                df_services = df_services.drop(['Captain', 'CarrierFuel', 'Commodities'], axis=0, errors='ignore')
                carriers[stat['CarrierID']]['Services'] = df_services.copy()
                carriers[stat['CarrierID']]['PendingDecom'] = stat['PendingDecommission']
        
        for carrier_buy in carrier_buys:
            if carrier_buy['CarrierID'] not in carriers.keys():
                carriers[carrier_buy['CarrierID']] = {'Callsign': carrier_buy['Callsign'], 'Name': 'Unknown', 'CMDRName': cmdr_names[carrier_owners[carrier_buy['CarrierID']]] if carrier_buy['CarrierID'] in carrier_owners.keys() and carrier_owners[carrier_buy['CarrierID']] in cmdr_names.keys() else None}
            carriers[carrier_buy['CarrierID']]['SpawnLocation'] = carrier_buy['Location']
            carriers[carrier_buy['CarrierID']]['TimeBought'] = datetime.strptime(carrier_buy['timestamp'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)

        for trit_deposit in trit_deposits:
            if trit_deposit['CarrierID'] in carriers.keys():
                if ('StatTime' not in carriers[trit_deposit['CarrierID']].keys() or datetime.strptime(trit_deposit['timestamp'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc) > carriers[trit_deposit['CarrierID']]['StatTime']) and ('Fuel' not in carriers[trit_deposit['CarrierID']].keys() or 'DepotTime' not in carriers[trit_deposit['CarrierID']]['Fuel'].keys()):
                    carriers[trit_deposit['CarrierID']]['Fuel'] = {'FuelLevel': trit_deposit['Total'], 'JumpRange': None, 'DepotTime': datetime.strptime(trit_deposit['timestamp'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)}

        for docking_perm in docking_perms:
            if docking_perm['CarrierID'] in carriers.keys():
                if 'DockingPerm' not in carriers[docking_perm['CarrierID']].keys():
                    carriers[docking_perm['CarrierID']]['DockingPerm'] = {'DockingAccess': docking_perm['DockingAccess'], 'AllowNotorious': docking_perm['AllowNotorious']}
        
        for carrier_location in carrier_locations:
            if carrier_location['CarrierID'] in carriers.keys():
                if 'CarrierLocation' not in carriers[carrier_location['CarrierID']].keys():
                    carriers[carrier_location['CarrierID']]['CarrierLocation'] = {'SystemName': carrier_location['StarSystem'], 'Body': None, 'BodyID': carrier_location['BodyID'], 'timestamp': datetime.strptime(carrier_location['timestamp'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)}

        jumps = pd.DataFrame(jump_requests + jump_cancels, columns=['CarrierID', 'timestamp', 'event', 'SystemName', 'Body', 'BodyID', 'DepartureTime']).sort_values('timestamp', ascending=False)
        for carrierID in carriers.keys():
            fc_jumps = jumps[jumps['CarrierID'] == carrierID][['timestamp', 'event', 'SystemName', 'Body', 'BodyID', 'DepartureTime']].copy()
            fc_jumps['timestamp'] = fc_jumps['timestamp'].apply(lambda x: datetime.strptime(x, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc))
            last_cancel = fc_jumps[fc_jumps['event'] == 'CarrierJumpCancelled'].iloc[0] if len(fc_jumps[fc_jumps['event'] == 'CarrierJumpCancelled']) > 0 else None
            carriers[carrierID]['last_cancel'] = last_cancel
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
            carriers[carrierID]['jumps'] = fc_jumps

            if 'SpawnLocation' not in carriers[carrierID].keys():
                carriers[carrierID]['SpawnLocation'] = 'Unknown'

            if 'TimeBought' not in carriers[carrierID].keys():
                carriers[carrierID]['TimeBought'] = None

            if 'CarrierLocation' not in carriers[carrierID].keys():
                carriers[carrierID]['CarrierLocation'] = {'SystemName': 'Unknown', 'Body': None, 'BodyID': None, 'timestamp': None}
            
            if 'Finance' not in carriers[carrierID].keys():
                if carriers[carrierID]['TimeBought'] is not None:
                    carriers[carrierID]['Finance'] = {'CarrierBalance': 0, 
                                                    'CmdrBalance': cmdr_balances[carrier_owners[carrierID]] if carrierID in carrier_owners.keys() and carrier_owners[carrierID] in cmdr_balances.keys() else None,
                                                    }
            
            if 'Fuel' not in carriers[carrierID].keys():
                if carriers[carrierID]['TimeBought'] is not None:
                    carriers[carrierID]['Fuel'] = {'FuelLevel': 500, 'JumpRange': 'Unknown'}
                else:
                    carriers[carrierID]['Fuel'] = {'FuelLevel': 'Unknown', 'JumpRange': 'Unknown'}

            if 'Services' not in carriers[carrierID].keys():
                if carriers[carrierID]['TimeBought'] is not None:
                    carriers[carrierID]['Services'] = pd.DataFrame({'Activated': {'BlackMarket': False, 'Refuel': False, 'Repair': False, 'Rearm': False, 'VoucherRedemption': False, 'Exploration': False, 'Shipyard': False, 'Outfitting': False}, 'Enabled': {'BlackMarket': False, 'Refuel': False, 'Repair': True, 'Rearm': False, 'VoucherRedemption': False, 'Exploration': False, 'Shipyard': False, 'Outfitting': False}})

            if 'StatTime' not in carriers[carrierID].keys():
                carriers[carrierID]['StatTime'] = None
            
            if 'DockingPerm' not in carriers[carrierID].keys():
                if carriers[carrierID]['TimeBought'] is not None:
                    carriers[carrierID]['DockingPerm'] = {'DockingAccess': 'all', 'AllowNotorious': False}
                else:
                    carriers[carrierID]['DockingPerm'] = {'DockingAccess': None, 'AllowNotorious': None}
            
            if 'SpaceUsage' not in carriers[carrierID].keys():
                carriers[carrierID]['SpaceUsage'] = {'Services': None, 'Cargo': None, 'BuyOrder': None, 'ShipPacks': None, 'ModulePacks': None, 'FreeSpace': None}

            if 'PendingDecom' not in carriers[carrierID].keys():
                carriers[carrierID]['PendingDecom'] = False
            
        if len(trade_orders) != 0:
            df_trade_orders = pd.DataFrame(trade_orders, columns=['CarrierID', 'timestamp', 'event', 'Commodity', 'Commodity_Localised', 'CancelTrade', 'PurchaseOrder', 'SaleOrder', 'Price']).sort_values('timestamp', ascending=True).reset_index(drop=True)
            for carrierID in carriers.keys():
                fc_trade_orders = df_trade_orders[df_trade_orders['CarrierID'] == carrierID].copy()
                if len(fc_trade_orders) > 0:
                    fc_active_trades = {}
                    for i in range(len(fc_trade_orders)):
                        order = fc_trade_orders.iloc[i]
                        commodity = order['Commodity']
                        if order['CancelTrade'] == True:
                            fc_active_trades.pop(commodity, None)
                        else:
                            fc_active_trades[commodity] = order
                else:
                    fc_active_trades = {}
                carriers[carrierID]['active_trades'] = pd.DataFrame(fc_active_trades.values(), columns=['CarrierID', 'timestamp', 'event', 'Commodity', 'Commodity_Localised', 'CancelTrade', 'PurchaseOrder', 'SaleOrder', 'Price']).sort_values('timestamp', ascending=True).reset_index(drop=True)
        else:
            for carrierID in carriers.keys():
                carriers[carrierID]['active_trades'] = pd.DataFrame({}, columns=['CarrierID', 'timestamp', 'event', 'Commodity', 'Commodity_Localised', 'CancelTrade', 'PurchaseOrder', 'SaleOrder', 'Price'])
        
        # for carrierID in carriers.keys():
        #     print(self.get_name(carrierID), '\n', carriers[carrierID]['active_trades'])
        
        self.carriers = carriers.copy()

    def update_carriers(self, now):
        carriers = self.carriers.copy()
        for carrierID in carriers.keys():
            data = carriers[carrierID]
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
        self.carriers_updated = carriers.copy()

    def get_carriers(self):
        return self.carriers_updated.copy()
    
    def get_data(self, now):
        return [generateInfo(self.get_carriers()[carrierID], now) for carrierID in self.sorted_ids()]
    
    def get_data_finance(self):
        df = pd.DataFrame([self.generate_info_finance(carrierID) for carrierID in self.sorted_ids()], columns=['Carrier Name', 'CMDR Name', 'Carrier Balance', 'CMDR Balance', 'Services Upkeep', 'Est. Jump Cost', 'Funded Till'])
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
        df = pd.DataFrame([self.generate_info_services(carrierID) for carrierID in self.sorted_ids()], columns=['Refuel', 'Repair', 'Rearm', 'Shipyard', 'Outfitting', 'Exploration', 'VistaGenomics', 'PioneerSupplies', 'Bartender', 'VoucherRedemption', 'BlackMarket'])
        df[['VistaGenomics', 'PioneerSupplies', 'Bartender']] = df[['VistaGenomics', 'PioneerSupplies', 'Bartender']].fillna('Off')
        df['Carrier Name'] = [self.get_name(carrierID) for carrierID in self.sorted_ids()]
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
        df['Carrier Name'] = [self.get_name(carrierID) for carrierID in self.sorted_ids()]
        df['Docking Permission'] = [self.generate_info_docking_perm(carrierID)[0] for carrierID in self.sorted_ids()]
        df['Allow Notorious'] = [self.generate_info_docking_perm(carrierID)[1] for carrierID in self.sorted_ids()]
        df['Services'] = [self.generate_info_space_usage(carrierID)[0] for carrierID in self.sorted_ids()]
        df['Cargo'] = [self.generate_info_space_usage(carrierID)[1] for carrierID in self.sorted_ids()]
        df['BuyOrder'] = [self.generate_info_space_usage(carrierID)[2] for carrierID in self.sorted_ids()]
        df['ShipPacks'] = [self.generate_info_space_usage(carrierID)[3] for carrierID in self.sorted_ids()]
        df['ModulePacks'] = [self.generate_info_space_usage(carrierID)[4] for carrierID in self.sorted_ids()]
        df['FreeSpace'] = [self.generate_info_space_usage(carrierID)[5] for carrierID in self.sorted_ids()]
        df['Time Bought'] = [self.generate_info_time_bought(carrierID=carrierID) for carrierID in self.sorted_ids()]
        df['Last Updated'] = [self.generate_info_stat_time(carrierID=carrierID) for carrierID in self.sorted_ids()]
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
    
    def get_carriers_pending_decom(self) -> list[int]|None:
        decomming = [i for i, carrierID in enumerate(self.sorted_ids()) if self.get_carriers()[carrierID]['PendingDecom'] == True]
        return decomming if len(decomming) > 0 else None
    
    def get_pending_decom(self, carrierID) -> bool:
        return self.get_carriers()[carrierID]['PendingDecom']
    
    def get_name(self, carrierID) -> str:
        return self.get_carriers()[carrierID]['Name']
    
    def get_callsign(self, carrierID) -> str:
        return self.get_carriers()[carrierID]['Callsign']
    
    def get_status(self, carrierID) -> str:
        return self.get_carriers()[carrierID]['status']
    
    def get_current_system(self, carrierID) -> str:
        return self.get_carriers()[carrierID]['current_system']
    
    def get_destination_system(self, carrier_ID) -> str|None:
        return self.get_carriers()[carrier_ID]['destination_system']
    
    def get_current_or_destination_system(self, carrierID) -> str:
        return self.get_destination_system(carrier_ID=carrierID) if self.get_status(carrierID=carrierID) == 'jumping' else self.get_current_system(carrierID=carrierID)
    
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
    
    def sorted_ids(self):
        return sorted(self.get_carriers().keys(), key=lambda x: self.get_time_bought(x) if self.get_time_bought(x) is not None else datetime(year=2020, month=6, day=9).replace(tzinfo=timezone.utc), reverse=False) # Assumes carrier bought at release if no buy event found
    
    def get_departure_hammer_countdown(self, carrierID) -> str|None:
        latest_depart = self.get_carriers()[carrierID]['latest_depart']
        return getHammerCountdown(latest_depart.to_datetime64()) if latest_depart is not None else None
    
    def get_formated_largest_order(self, carrierID) -> str|None:
        df_active_trades = self.generate_info_trade(carrierID=carrierID)
        if len(df_active_trades) == 0:
            return None
        else:
            df_active_trades['Amount'] = df_active_trades['Amount'].str.replace(',', '').astype(float)
            df_active_trades.sort_values('Amount', ascending=False, inplace=True)
            largest_order = df_active_trades.iloc[0]
            commodity = largest_order['Commodity']
            amount = largest_order['Amount']
            amount = round(amount / 500) * 500 / 1000
            if amount % 1 == 0:
                amount = int(amount)
            order_type = largest_order['Trade Type'].lower()
            return (order_type, commodity, amount)
            
    def get_data_trade(self) -> tuple[pd.DataFrame, list[int]|None]:
        trades = [self.generate_info_trade(carrierID) for carrierID in self.sorted_ids()]
        df = pd.concat(trades, axis=0, ignore_index=True) if len(trades) > 0 else pd.DataFrame(columns=['CarrierID', 'Carrier Name', 'Trade Type', 'Amount', 'Commodity', 'Price', 'Time Set (Local)', 'Pending Decom'])
        self.trad_carrierIDs = df['CarrierID']
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
    elif body is None or type(body) is float:
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
        if system in body:
            result_system, result_body = system, body.replace(f'{system} ', '')
        else: 
            result_system, result_body = system, body
    
    if result_system in ladder_systems.keys():
        result_system = f'{ladder_systems[result_system]} ({result_system})'
    return result_system, result_body


def generateInfo(carrier, now):
    location_system, location_body = getLocation(carrier['current_system'], carrier['current_body'], carrier['current_body_id'])
    fuel_level = carrier['Fuel']['FuelLevel']
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
            f"{h:.0f} h {m:02.0f} m {s:02.0f} s"
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
            f"{h:.0f} h {m:02.0f} m {s:02.0f} s"
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
            f"{h:.0f} h {m:02.0f} m {s:02.0f} s"
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
            )

if __name__ == '__main__':
    model = CarrierModel(getJournalPath())
    now = datetime.now(timezone.utc)
    model.update_carriers(now)
    print(pd.DataFrame(model.get_data(now), columns=[
            'Carrier Name', 'Carrier ID', 'Fuel', 'Current System', 'Body',
            'Status', 'Destination System', 'Body', 'Timer'
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