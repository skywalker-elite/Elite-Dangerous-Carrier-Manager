"""Model contracts use selected independent values rather than whole-object snapshots."""
import pickle
from copy import deepcopy
from datetime import timedelta

import pandas as pd
import pytest

from config import ASSUME_DECCOM_AFTER, CD, CD_cancel, JUMPLOCK, PADLOCK
from model import CarrierModel, getLocation
from tests.journal_helpers import (NOW, append_events, assert_tables_render, event,
                                   freeze_clock, make_model, sample_events, stamp, write_journal)


@pytest.fixture(autouse=True)
def fixed_time(monkeypatch):
    freeze_clock(monkeypatch)


@pytest.fixture
def carrier(tmp_path):
    return make_model(tmp_path)


def refresh(model, path, *records, now=NOW):
    append_events(path, *records)
    model.read_journals()
    model.update_carriers(now)


def test_complete_journal_has_expected_finance_services_and_tables(carrier):
    assert carrier.get_name(1) == 'Test Carrier'
    assert carrier.get_callsign(1) == 'ABC-123'
    assert carrier.get_owned_carrier('F1') == 1
    assert carrier.get_cmdr_name(1) == 'Commander F1'
    assert carrier.get_finance(1) == {'CarrierBalance': 1_000_000_000, 'CmdrBalance': 2_000_000_000}
    assert carrier.get_carriers()[1]['Fuel'] == {'FuelLevel': 500, 'JumpRange': 250}
    assert carrier.generate_info_services(1).to_dict() == {'Refuel': 'Active', 'Repair': 'Paused', 'Rearm': 'Off'}
    assert carrier.calculate_upkeep(1) == 7_250_000
    assert carrier.calculate_average_jump_costs(1) == 0
    assert carrier.get_data_finance()[0][2:7] == ['1,000,000,000', '2,000,000,000', '3,000,000,000', '7,250,000', '0']
    assert carrier.generate_info_docking_perm(1) == ('All', 'No')
    assert carrier.get_current_system(1) == 'Sol'
    assert carrier.get_current_body(1) == 'Star'
    assert carrier.generate_info_cmdr_location(1) == ('Sol', 'Test Carrier')
    assert carrier.get_formatted_largest_order(1) == ('loading', 'Tritium', 2, 50000)
    assert carrier.get_formatted_largest_order(1, in_tons=True) == ('loading', 'Tritium', 2000, 50000)
    assert carrier.get_formatted_largest_order(1, filter_commodity='Gold') is None
    assert carrier.get_trade_history(1)['Commodity'].tolist() == ['Tritium']
    assert_tables_render(carrier)


def test_incremental_fuel_and_docking_permissions(tmp_path):
    carrier = make_model(tmp_path)
    path = next(tmp_path.glob('Journal.*.log'))
    refresh(carrier, path, event('CarrierDepositFuel', 1, CarrierID=1, Total=675),
            event('CarrierDockingPermission', 2, CarrierID=1, DockingAccess='friends', AllowNotorious=True))
    assert carrier.get_carriers()[1]['Fuel']['FuelLevel'] == 675
    assert carrier.generate_info_docking_perm(1) == ('Friends', 'Yes')
    carrier.read_journals()
    carrier.update_carriers(NOW)
    assert carrier.get_carriers()[1]['Fuel']['FuelLevel'] == 675


@pytest.mark.parametrize('permission,expected', [('all', 'All'), ('friends', 'Friends'), ('squadron', 'Squadron'),
                                               ('squadronfriends', 'Squadron&Friends'), ('none', 'None'), ('invalid', 'Unknown')])
def test_permission_display_mapping(tmp_path, permission, expected):
    events = sample_events()
    events[3]['DockingAccess'] = permission
    result = make_model(tmp_path, events)
    assert result.generate_info_docking_perm(1) == (expected, 'No')


def test_squadron_carrier_has_separate_upkeep_and_whitelist(tmp_path):
    events = sample_events() + sample_events(fid='F2', carrier_id=2, name='Squadron', callsign='DEF-456', squadron=True)
    carrier = make_model(tmp_path, events)
    assert carrier.is_squadron_carrier(2)
    assert 2 not in carrier.carrier_owners
    assert carrier.calculate_upkeep(2) == 12_250_000
    assert carrier.generate_info_docking_perm(2) == ('Squadron', 'No')
    carrier.update_ignore_list()
    assert carrier.sorted_ids_display() == [1]
    carrier.reset_ignore_list()
    carrier.add_sfc_whitelist(['DEF-456'])
    carrier.update_ignore_list()
    assert carrier.sorted_ids_display() == [1, 2]
    assert_tables_render(carrier)


def test_custom_order_ignore_lists_and_squadron_abbreviation(tmp_path):
    first = sample_events()
    second = sample_events(fid='F2', carrier_id=2, name='Second', callsign='DEF-456')
    write_journal(tmp_path, first, 'Journal.2026-01-02T110000.01.log')
    write_journal(tmp_path, second)
    carrier = CarrierModel([str(tmp_path)])
    carrier.set_custom_order(['DEF-456', 'ABC-123'])
    assert carrier.sorted_ids() == [2, 1]
    carrier.add_ignore_list(['DEF-456', 'DEF-456', 'missing'])
    assert carrier.sorted_ids_display() == [1]
    assert carrier.get_ignore_list() == [2]
    returned = carrier.get_ignore_list()
    returned.clear()
    assert carrier.sorted_ids_display() == [1]
    carrier.reset_ignore_list()
    assert carrier.sorted_ids_display() == [2, 1]
    carrier.set_squadron_abbv_mapping([{'Test Squadron': 'abcdxy'}])
    assert carrier.generate_info_squadron_name(1) == 'ABCD'


def jump(seconds=0, depart=900, system='Achenar', carrier_id=1):
    return event('CarrierJumpRequest', seconds, CarrierID=carrier_id,
                 SystemName=system, Body=f'{system} 1', BodyID=1, DepartureTime=stamp(depart))


@pytest.mark.parametrize('offset,status', [(-1, 'jumping'), (0, 'cool_down'),
                                         (CD.total_seconds() - 1, 'cool_down'),
                                         (CD.total_seconds(), 'idle')])
def test_departure_and_cooldown_boundaries(tmp_path, offset, status):
    carrier = make_model(tmp_path, sample_events() + [jump()])
    carrier.update_carriers(NOW + timedelta(seconds=900 + offset))
    assert carrier.get_status(1) == status
    assert carrier.get_jump_timer_in_seconds(carrier.get_latest_jump_plot(1), carrier.get_latest_departure(1)) == 900
    assert carrier.get_current_or_destination_system(1) == 'Achenar'
    if status == 'jumping':
        assert carrier.get_current_system(1) == 'Sol'
        assert carrier.get_destination_body(1) == '1'
    else:
        assert carrier.get_current_system(1) == 'Achenar'
        assert carrier.get_destination_system(1) is None
    assert len(carrier.get_data(NOW + timedelta(seconds=900 + offset))) == 1


@pytest.mark.parametrize('remaining', [JUMPLOCK.total_seconds(), PADLOCK.total_seconds(), 1])
def test_jump_table_renders_configured_lock_boundaries(tmp_path, remaining):
    carrier = make_model(tmp_path, sample_events() + [jump()])
    at = NOW + timedelta(seconds=900 - remaining)
    carrier.update_carriers(at)
    row = carrier.get_data(at)[0]
    assert row[0:2] == ('Test Carrier', 'ABC-123')
    assert carrier.get_status(1) == 'jumping'
    assert row[6] == 'Achenar'


@pytest.mark.parametrize('offset,status', [(0, 'cool_down_cancel'), (CD_cancel.total_seconds()-1, 'cool_down_cancel'),
                                         (CD_cancel.total_seconds(), 'idle')])
def test_cancel_boundary_removes_jump_in_incremental_read(tmp_path, offset, status):
    carrier = make_model(tmp_path, sample_events() + [jump()])
    path = next(tmp_path.glob('Journal.*.log'))
    refresh(carrier, path, event('CarrierJumpCancelled', 1, CarrierID=1), now=NOW + timedelta(seconds=1+offset))
    assert carrier.get_status(1) == status
    assert carrier.get_latest_departure(1) is None
    assert carrier.get_current_system(1) == 'Sol'


def test_latest_stats_replace_balance_and_services(tmp_path):
    records = sample_events()
    newer = deepcopy(records[3])
    newer['timestamp'] = stamp(2)
    newer['Finance']['CarrierBalance'] = 123456
    newer['FuelLevel'] = 890
    newer['Crew'][2]['Enabled'] = True
    carrier = make_model(tmp_path, records + [newer])
    assert carrier.get_finance(1)['CarrierBalance'] == 123456
    assert carrier.get_carriers()[1]['Fuel']['FuelLevel'] == 890
    assert carrier.calculate_upkeep(1) == 8_000_000


def test_average_jump_cost_counts_recent_jumps_only(tmp_path):
    recent = [jump(-index * 86400, -index * 86400 + 900) for index in range(8)]
    old = jump(-100 * 86400, -100 * 86400 + 900)
    carrier = make_model(tmp_path, sample_events() + [old] + recent)
    assert carrier.calculate_average_jump_costs(1) == 100000


def test_itinerary_docking_undocking_and_jump_times(tmp_path):
    carrier = make_model(tmp_path)
    path = next(tmp_path.glob('Journal.*.log'))
    assert carrier.get_cmdr_location('F1', NOW - timedelta(seconds=46)) == ('Sol', 'ABC-123')
    refresh(carrier, path, event('Undocked', 1, StationName='ABC-123', MarketID=1),
            event('FSDJump', 2, StarSystem='Achenar'),
            event('Docked', 3, StarSystem='Achenar', StationName='Dawes Hub', MarketID=12))
    assert carrier.get_cmdr_location('F1', NOW + timedelta(seconds=1)) == ('Sol', None)
    assert carrier.get_cmdr_location('F1', NOW + timedelta(seconds=2)) == ('Achenar', None)
    assert carrier.get_cmdr_current_location('F1') == ('Achenar', 'Dawes Hub')
    assert carrier.get_cmdr_current_location('missing') == (None, None)


def test_trade_replacement_cancellation_and_unloading(tmp_path):
    carrier = make_model(tmp_path)
    path = next(tmp_path.glob('Journal.*.log'))
    refresh(carrier, path, event('CarrierTradeOrder', 1, CarrierID=1, Commodity='tritium',
            CancelTrade=False, PurchaseOrder=0, SaleOrder=1250, Price=51000))
    assert carrier.get_formatted_largest_order(1, in_tons=True) == ('unloading', 'Tritium', 1250, 51000)
    assert len(carrier.get_active_trades(1)) == 1
    refresh(carrier, path, event('CarrierTradeOrder', 2, CarrierID=1, Commodity='tritium', CancelTrade=True))
    assert carrier.get_active_trades(1).empty
    assert carrier.get_data_trade()[0] == []
    assert carrier.get_formatted_largest_order(1) is None


@pytest.mark.known_defect('MD-001')
def test_trade_history_survives_incremental_updates(tmp_path):
    carrier = make_model(tmp_path)
    path = next(tmp_path.glob('Journal.*.log'))
    refresh(carrier, path, event('CarrierTradeOrder', 1, CarrierID=1, Commodity='tritium',
            CancelTrade=False, PurchaseOrder=1000, SaleOrder=0, Price=52000))
    history = carrier.get_trade_history(1)
    assert len(history) == 2
    assert set(history['Price']) == {'50,000', '52,000'}


@pytest.mark.known_defect('MD-002')
def test_missing_trade_events_have_empty_history(tmp_path):
    carrier = make_model(tmp_path, [r for r in sample_events() if r['event'] != 'CarrierTradeOrder'])
    assert_tables_render(carrier)
    assert carrier.get_trade_history(1).empty
    assert carrier.get_formatted_largest_order(1) is None


@pytest.mark.parametrize('squadron,capacity', [(False, 25000), (True, 60000)])
def test_capacity_filter_uses_current_exclusive_cutoff(carrier, squadron, capacity):
    result = carrier.filter_likely_active_trades(pd.DataFrame({'Amount': [capacity], 'Commodity': ['Tritium']}),
                                               is_squadron_carrier=squadron)
    assert result.empty


def test_capacity_filter_keeps_only_orders_that_fit(carrier):
    trades = pd.DataFrame({'Amount': [10000, 14000, 2000], 'Commodity': ['Tritium', 'Gold', 'Silver']})
    assert carrier.filter_likely_active_trades(trades)['Commodity'].tolist() == ['Tritium', 'Gold']
    assert len(trades) == 3


@pytest.mark.known_defect('MD-004')
def test_largest_order_when_capacity_filter_removes_every_row(tmp_path):
    records = sample_events()
    records[-1]['PurchaseOrder'] = 30000
    carrier = make_model(tmp_path, records)
    assert carrier.get_formatted_largest_order(1) is None


@pytest.mark.known_defect('MD-005')
def test_recent_jump_missing_departure_time_preserves_usable_model(tmp_path):
    damaged = jump()
    del damaged['DepartureTime']
    carrier = make_model(tmp_path, sample_events() + [damaged])
    assert carrier.get_name(1) == 'Test Carrier'
    assert_tables_render(carrier)


def test_legacy_jump_without_departure_time_uses_fifteen_minutes(tmp_path):
    old = jump()
    old['timestamp'] = '2022-01-01T12:00:00Z'
    del old['DepartureTime']
    carrier = make_model(tmp_path, sample_events() + [old])
    assert carrier.get_latest_departure(1).isoformat() == '2022-01-01T12:15:00+00:00'


def test_full_incremental_and_cache_resume_have_equivalent_supported_outputs(tmp_path):
    records = sample_events()
    updates = [event('LoadGame', 1, FID='F1', Commander='Renamed', Credits=123000),
               dict(records[3], timestamp=stamp(2)),
               event('CarrierDepositFuel', 3, CarrierID=1, Total=625),
               event('CarrierLocation', 4, CarrierID=1, StarSystem='Achenar', BodyID=0)]
    full = make_model(tmp_path / 'full', records + updates)
    incremental = make_model(tmp_path / 'incremental', records)
    refresh(incremental, next((tmp_path / 'incremental').glob('Journal.*.log')), *updates)
    cached_seed = make_model(tmp_path / 'cached', records)
    cached_reader = pickle.loads(pickle.dumps(cached_seed.journal_reader))
    cached = CarrierModel([], journal_reader=cached_reader)
    refresh(cached, next((tmp_path / 'cached').glob('Journal.*.log')), *updates)
    for item in [full, incremental, cached]:
        assert item.get_current_system(1) == 'Achenar'
        assert item.get_finance(1) == {'CarrierBalance': 1_000_000_000, 'CmdrBalance': 123000}
        assert item.get_carriers()[1]['Fuel']['FuelLevel'] == 625
        assert item.get_cmdr_name(1) == 'Renamed'
        assert item.get_formatted_largest_order(1, in_tons=True) == ('loading', 'Tritium', 2000, 50000)
        assert_tables_render(item)


@pytest.mark.known_defect('MD-006')
def test_initial_and_incremental_docking_permissions_agree(tmp_path):
    update = event('CarrierDockingPermission', 1, CarrierID=1, DockingAccess='friends', AllowNotorious=True)
    full = make_model(tmp_path / 'full', sample_events() + [update])
    assert full.generate_info_docking_perm(1) == ('Friends', 'Yes')


def test_decommission_state_and_expiry(tmp_path, monkeypatch):
    records = sample_events()
    records[3]['PendingDecommission'] = True
    carrier = make_model(tmp_path, records)
    assert carrier.get_carriers_pending_decom() == [1]
    assert carrier.get_rows_pending_decom() == [0]
    assert carrier.get_data_trade()[1] == [0]
    freeze_clock(monkeypatch, NOW + ASSUME_DECCOM_AFTER + timedelta(days=1))
    carrier.update_ignore_list()
    assert carrier.sorted_ids_display() == []


@pytest.mark.parametrize('system,body,body_id,expected', [
    ('Sol', 'Sol 3', 3, ('Sol', '3')), ('Sol', None, 0, ('Sol', 'Star')),
    ('Sol', None, 6, ('Sol', 'Unknown')), ('HIP 58832', None, 16, ('N0 (HIP 58832)', '6')),
])
def test_location_names(system, body, body_id, expected):
    assert getLocation(system, body, body_id) == expected
