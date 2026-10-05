"""Small synthetic journals: no player files, credentials, or wall-clock dependency."""
import json
from datetime import datetime, timedelta, timezone

NOW = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)


def stamp(seconds=0):
    return (NOW + timedelta(seconds=seconds)).strftime('%Y-%m-%dT%H:%M:%SZ')


def event(name, seconds=0, **fields):
    return dict(event=name, timestamp=stamp(seconds), **fields)


def sample_events(fid='F1', carrier_id=1, name='Test Carrier', callsign='ABC-123', squadron=False):
    """Return fresh complete records covering each major model input."""
    return [
        event('Commander', -60, FID=fid, Name=f'Commander {fid}'),
        event('LoadGame', -59, FID=fid, Commander=f'Commander {fid}', Credits=2_000_000_000),
        event('CarrierBuy', -58, CarrierID=carrier_id, Callsign=callsign, Location='Sol'),
        event('CarrierStats', -50, CarrierID=carrier_id, Callsign=callsign, Name=name,
              CarrierType='SquadronCarrier' if squadron else 'FleetCarrier',
              Finance={'CarrierBalance': 1_000_000_000}, FuelLevel=500, JumpRangeCurr=250,
              SpaceUsage={'Crew': 1000, 'Cargo': 2000, 'CargoSpaceReserved': 3000,
                          'ShipPacks': 400, 'ModulePacks': 600, 'FreeSpace': 18000},
              Crew=[{'CrewRole': 'Captain', 'Activated': True, 'Enabled': True},
                    {'CrewRole': 'Refuel', 'Activated': True, 'Enabled': True},
                    {'CrewRole': 'Repair', 'Activated': True, 'Enabled': False},
                    {'CrewRole': 'Rearm', 'Activated': False, 'Enabled': False}],
              PendingDecommission=False, DockingAccess='all', AllowNotorious=False),
        event('CarrierLocation', -49, CarrierID=carrier_id, StarSystem='Sol', BodyID=0),
        event('SquadronStartup', -48, SquadronName='Test Squadron'),
        event('FSDJump', -47, StarSystem='Sol'),
        event('Docked', -46, StarSystem='Sol', StationName=callsign, MarketID=carrier_id),
        event('CarrierTradeOrder', -45, CarrierID=carrier_id, Commodity='tritium',
              Commodity_Localised='Tritium', CancelTrade=False, PurchaseOrder=2000,
              SaleOrder=0, Price=50000),
    ]


def append_events(path, *events):
    with path.open('ab') as stream:
        for record in events:
            stream.write((json.dumps(record, ensure_ascii=False) + '\n').encode('utf-8'))


def write_journal(tmp_path, events, filename='Journal.2026-01-02T120000.01.log'):
    tmp_path.mkdir(parents=True, exist_ok=True)
    result = tmp_path / filename
    result.write_bytes(b'')
    append_events(result, *events)
    return result


def freeze_clock(monkeypatch, now=NOW):
    import model

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz is not None else now.astimezone().replace(tzinfo=None)

    monkeypatch.setattr(model, 'datetime', FrozenDateTime)


def make_model(tmp_path, events=None):
    from model import CarrierModel
    write_journal(tmp_path, sample_events() if events is None else events)
    return CarrierModel([str(tmp_path)])


def assert_tables_render(model):
    """Exercise all table-facing APIs; assert row identity without presentation snapshots."""
    model.update_carriers(NOW)
    ids = model.sorted_ids_display()
    names = [model.get_name(cid) for cid in ids]
    for rows in (model.get_data(NOW), model.get_data_services(), model.get_data_misc(),
                 model.get_data_cmdr()):
        assert [row[0] for row in rows] == names
    finance = model.get_data_finance()
    assert [row[0] for row in finance[:-1]] == names
    assert len(finance) == len(ids) + 1
    trades, _ = model.get_data_trade()
    assert all(row[0] in names for row in trades)
    assert isinstance(model.get_data_active_journals(), list)
    for cid in ids:
        model.get_formatted_largest_order(cid)
