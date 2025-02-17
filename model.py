import pandas as pd
from os import listdir, path
import re
import json
from numpy import datetime64, nan
from datetime import datetime, timezone, timedelta
from config import journal_path, PADLOCK, CD, JUMPLOCK, ladder_systems

class CarrierModel:
    def __init__(self):
        self.carriers = {}
        self.carriers_updated = {}
        self.active_timer = False
        self.manual_timers = []
        self.read_journals()

    def read_journals(self, journal_path=journal_path):
        files = listdir(journal_path)
        r = r'^Journal\.\d{4}-\d{2}-\d{2}T\d{6}\.\d{2}\.log$'
        journals = sorted([i for i in files if re.fullmatch(r, i)], reverse=True)
        # jumps = []
        load_games = []
        jump_requests = []
        jump_cancels = []
        stats = []
        trade_orders = []
        carrier_buys = []
        carrier_owners = {}
        for journal in journals:
            with open(path.join(journal_path, journal), 'r', encoding='utf-8') as f:
                items = []
                for i in f.readlines():
                    try:
                        items.append(json.loads(i))
                    except json.decoder.JSONDecodeError: # ignore ill-formated entries
                        continue
                fid_temp = [i['FID'] for i in items if i['event'] =='Commander']
                if len(fid_temp) > 0:
                    if all(i == fid_temp[0] for i in fid_temp):
                        fid = fid_temp[0]
                    else:
                        fid = None
                    # print(fid)
                # jumps.extend([i for i in items if i['event'] == 'CarrierJump'])
                for item in reversed(items): # Parse from new to old
                    if item['event'] == 'LoadGame':
                        load_games.append(item)
                    if item['event'] == 'CarrierJumpRequest':
                        jump_requests.append(item)
                    if item['event'] == 'CarrierJumpCancelled':
                        jump_cancels.append(item)
                    if item['event'] == 'CarrierStats':
                        stats.append(item)
                        if item['CarrierID'] not in carrier_owners.keys() and fid is not None:
                            carrier_owners[item['CarrierID']] = fid
                    if item['event'] == 'CarrierTradeOrder':
                        trade_orders.append(item)
                    if item['event'] == 'CarrierBuy':
                        carrier_buys.append(item)
                    
        cmdr_balances = {}
        for load_game in load_games:
            if load_game['FID'] not in cmdr_balances.keys():
                cmdr_balances[load_game['FID']] = load_game['Credits']
        
        carriers = {}
        for stat in stats:
            if stat['CarrierID'] not in carriers.keys():
                carriers[stat['CarrierID']] = {'Callsign': stat['Callsign'], 'Name': stat['Name']}
                carriers[stat['CarrierID']]['Finance'] = {'CarrierBalance': stat['Finance']['CarrierBalance'], 
                                                          'CmdrBalance': cmdr_balances[carrier_owners[stat['CarrierID']]] if stat['CarrierID'] in carrier_owners.keys() else None,
                                                          'ReserveBalance': stat['Finance']['ReserveBalance'], 
                                                          'AvailableBalance': stat['Finance']['AvailableBalance'],
                                                          }
        
        for carrier_buy in carrier_buys:
            if carrier_buy['CarrierID'] not in carriers.keys():
                carriers[carrier_buy['CarrierID']] = {'Callsign': carrier_buy['Callsign'], 'Name': 'Unknown'}
            carriers[carrier_buy['CarrierID']]['SpawnLocation'] = carrier_buy['Location']
            carriers[carrier_buy['CarrierID']]['TimeBought'] = datetime.strptime(carrier_buy['timestamp'], '%Y-%m-%dT%H:%M:%SZ')

        jumps = pd.DataFrame(jump_requests + jump_cancels)
        df_trade_orders = pd.DataFrame(trade_orders, columns=['CarrierID', 'timestamp', 'event', 'Commodity', 'Commodity_Localised', 'CancelTrade', 'PurchaseOrder', 'SaleOrder']).sort_values('timestamp', ascending=False).reset_index(drop=True) if len(trade_orders) != 0 else None
        # print(df_trade_orders.head())
        for carrierID in carriers.keys():
            fc_jumps = jumps[jumps['CarrierID'] == carrierID][['timestamp', 'event', 'SystemName', 'Body', 'BodyID', 'DepartureTime']].copy()
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
            fc_jumps['timestamp'] = fc_jumps['timestamp'].apply(lambda x: datetime.strptime(x, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc))
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
            
            # TODO: need to map by commodity
            if df_trade_orders is not None:
                fc_trade_orders = df_trade_orders[df_trade_orders['CarrierID'] == carrierID].copy()
                if len(fc_trade_orders) > 0:
                    fc_last_order = df_trade_orders[df_trade_orders['CarrierID'] == carrierID].iloc[0][['timestamp', 'event', 'Commodity', 'Commodity_Localised', 'CancelTrade', 'PurchaseOrder', 'SaleOrder']].copy()
                    # print(fc_last_order)
                else:
                    fc_last_order = None
            else:
                fc_last_order = None
            carriers[carrierID]['last_trade'] = fc_last_order

        self.carriers = carriers.copy()

    def update_carriers(self, now):
        # now = datetime.now(timezone.utc)
        carriers = self.carriers.copy()
        for carrierID in carriers.keys():
            data = carriers[carrierID]
            if len(data['jumps']) == 0:
                data['latest_depart'] = None
                latest_body = None
                latest_body_id = None
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
            if time_diff is not None and time_diff < timedelta(0):
                self.active_timer = True
                data['status'] = 'jumping'
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
            else:
                self.active_timer = False
                data['status'] = 'idle'
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
        df = pd.DataFrame([self.generate_info_finance(carrierID) for carrierID in self.sorted_ids()], columns=['Carrier Name', 'Carrier Balance', 'CMDR Balance', 'Reserve Balance', 'Available Balance'])
        # handles unknown cmdr balance
        idx_no_cmdr = df[df['CMDR Balance'].isna()].index
        df.loc[idx_no_cmdr, 'CMDR Balance'] = 0
        df.insert(3, 'Total', df['Carrier Balance'].astype(int) + df['CMDR Balance'].astype(int))
        df = pd.concat([df, pd.DataFrame([['Total', df.iloc[:,1].astype(int).sum(), df.iloc[:,2].astype(int).sum(), df.iloc[:,3].astype(int).sum(), df.iloc[:,4].astype(int).sum(), df.iloc[:,5].astype(int).sum()]], columns=df.columns)], axis=0, ignore_index=True)
        df = df.astype('object') # to comply with https://pandas.pydata.org/docs/dev/whatsnew/v2.1.0.html#deprecated-silent-upcasting-in-setitem-like-series-operations
        df.iloc[:, 1:] = df.iloc[:, 1:].apply(lambda x: [f'{xi:,}' for xi in x])
        df.loc[idx_no_cmdr, 'CMDR Balance'] = 'Unknown'
        return df.values.tolist()
    
    def generate_info_finance(self, carrierID):
        return (self.get_name(carrierID=carrierID), *[n for n in self.get_finance(carrierID).values()])
    
    def get_finance(self, carrierID):
        return self.get_carriers()[carrierID]['Finance']

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
    
    def sorted_ids(self):
        return sorted(self.get_carriers().keys(), key=lambda x: self.carriers[x]['TimeBought'] if 'TimeBought' in self.carriers[x].keys() else datetime(year=2020, month=6, day=9), reverse=False) # Assumes carrier bought at release if no buy event found
    
    def get_departure_hammer_countdown(self, carrierID) -> str:
        return getHammerCountdown(self.get_carriers()[carrierID]['latest_depart'].to_datetime64())
    
    def get_formated_last_order(self, carrierID) -> str:
        last_trade = self.get_carriers()[carrierID]['last_trade']
        if last_trade is None or last_trade['CancelTrade'] == True:
            return None
        else:
            if last_trade.notna()['PurchaseOrder']:
                commodity = last_trade['Commodity_Localised'] if last_trade.notna()['Commodity_Localised'] else last_trade['Commodity'].capitalize() #TODO: this only works if client is using English
                amount = round(last_trade['PurchaseOrder'] / 500) * 500 / 1000
                if amount % 1 == 0:
                    amount = int(amount)
                return ('loading', commodity, amount)
            elif last_trade.notna()['SaleOrder']:
                commodity = last_trade['Commodity_Localised'] if last_trade.notna()['Commodity_Localised'] else last_trade['Commodity'].capitalize() #TODO: this only works if client is using English
                amount = round(last_trade['SaleOrder'] / 500) * 500 / 1000
                if amount % 1 == 0:
                    amount = int(amount)
                return ('unloading', commodity, amount)

def getLocation(system, body, body_id):
    if body is None or type(body) is float:
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


def generateInfo(data, now):
    location_system, location_body = getLocation(data['current_system'], data['current_body'], data['current_body_id'])
    if data['status'] == 'jumping':
        destination_system, destination_body = getLocation(data['destination_system'], data['destination_body'], data['destination_body_id'])
        # now = datetime.now(timezone.utc)
        time_diff = data['latest_depart'] - now
        h, m, s = getHMS(time_diff.total_seconds())
        return (
            f"{data['Name']}", 
            f"{data['Callsign']}", 
            f"{location_system}", 
            f"{location_body}", 
            f"Pad Locked" if time_diff < PADLOCK else "Jump Locked" if time_diff < JUMPLOCK else f"Jumping",
            f"{destination_system}", 
            f"{destination_body}", 
            f"{h:.0f} h {m:02.0f} m {s:02.0f} s"
            )
    elif data['status'] == 'cool_down':
        # now = datetime.now(timezone.utc)
        time_diff = CD - (now - data['latest_depart'])
        h, m, s = getHMS(time_diff.total_seconds())
        return (
            f"{data['Name']}", 
            f"{data['Callsign']}", 
            f"{location_system}", 
            f"{location_body}", 
            f"Cooling Down",
            f"", 
            f"",
            f"{h:.0f} h {m:02.0f} m {s:02.0f} s"
            )
    else:
        return (
            f"{data['Name']}", 
            f"{data['Callsign']}", 
            f"{location_system}", 
            f"{location_body}", 
            f"Idle",
            f"", 
            f"",
            f"",
            )

def getHMS(seconds):
    m, s = divmod(round(seconds), 60)
    h, m = divmod(m, 60)
    return h, m, s

def formatForSort(s:str) -> str:
    out = ''
    for si in s:
        if si.isdigit():
            out += chr(ord(si) + 49)
        else:
            out += si
    return out

def getHammerCountdown(dt:datetime64) -> str:
    unix_time = dt.astype('datetime64[s]').astype('int')
    return f'<t:{unix_time}:R>'

if __name__ == '__main__':
    model = CarrierModel()
    now = datetime.now(timezone.utc)
    model.update_carriers(now)
    print(pd.DataFrame(model.get_data(now)))
    print(pd.DataFrame(model.get_data_finance()))