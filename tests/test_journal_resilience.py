"""Recovery contracts. Known defects remain ordinary failing assertions in diagnostics."""
import json
import pickle
from copy import deepcopy

import pytest

from model import CarrierModel, JournalReader
from tests.journal_helpers import (NOW, append_events, assert_tables_render, event,
                                   freeze_clock, sample_events, write_journal)


@pytest.fixture(autouse=True)
def fixed_time(monkeypatch):
    freeze_clock(monkeypatch)


def read_model(directory):
    result = CarrierModel([str(directory)])
    assert_tables_render(result)
    return result


@pytest.mark.parametrize('position', [0, 4, 9], ids=['before', 'between', 'after'])
@pytest.mark.parametrize('broken', [b'{"event" "CarrierStats"}\n', b'{"event":\n', b'not JSON\n'])
def test_missing_punctuation_is_skipped_and_later_events_survive(tmp_path, position, broken):
    events = sample_events()
    path = write_journal(tmp_path, events[:position])
    with path.open('ab') as stream:
        stream.write(broken)
    append_events(path, *events[position:])
    result = read_model(tmp_path)
    for _ in range(3):
        result.read_journals()
    assert result.get_finance(1)['CarrierBalance'] == 1_000_000_000
    assert len(result.journal_reader.get_items()[4]) == 1
    assert len(result.get_active_trades(1)) == 1
    assert result.get_current_system(1) == 'Sol'


@pytest.mark.parametrize('record', [None, [], 42, 'text', {}, {'evnt': 'CarrierStats'},
                                  {'event': 'Commander'}, {'event': 'CarrierStats', 'timestamp': '2026-01-02T12:00:00Z'}])
@pytest.mark.known_defect('JR-001')
def test_structurally_damaged_record_does_not_block_next_valid_record(tmp_path, record):
    path = write_journal(tmp_path, sample_events())
    result = read_model(tmp_path)
    append_events(path, record, event('CarrierDepositFuel', 1, CarrierID=1, Total=650))
    result.read_journals()
    result.update_carriers(NOW)
    assert result.get_carriers()[1]['Fuel']['FuelLevel'] == 650
    assert_tables_render(result)


@pytest.mark.parametrize('position', [0, 4, 9])
@pytest.mark.known_defect('JR-002')
def test_deleted_utf8_byte_does_not_abort_whole_file(tmp_path, position):
    events = sample_events()
    path = write_journal(tmp_path, events[:position])
    line = json.dumps(event('Music', MusicTrack='Café'), ensure_ascii=False).encode('utf-8')
    index = line.index('é'.encode('utf-8'))
    damaged = line[:index] + line[index + 1:]
    with path.open('ab') as stream:
        stream.write(damaged + b'\n')
    append_events(path, *events[position:])
    result = read_model(tmp_path)
    assert result.get_name(1) == 'Test Carrier'


@pytest.mark.parametrize('timestamp', [None, 123, '2026-02-30T12:00:00Z', '2026-01-02T12:0:00Z', 'invalid'])
@pytest.mark.known_defect('JR-003')
def test_invalid_timestamp_does_not_discard_valid_carrier_state(tmp_path, timestamp):
    events = sample_events()
    damaged = deepcopy(events[3])
    damaged['timestamp'] = timestamp
    damaged['FuelLevel'] = 123
    write_journal(tmp_path, events + [damaged])
    result = read_model(tmp_path)
    assert result.get_carriers()[1]['Fuel']['FuelLevel'] == 500


@pytest.mark.parametrize('field,value', [('Finance', None), ('Finance', {}), ('SpaceUsage', {}),
                                        ('SpaceUsage', {'Crew': 1000, 'Cargo': 'invalid',
                                                        'CargoSpaceReserved': 3000, 'ShipPacks': 400,
                                                        'ModulePacks': 600, 'FreeSpace': 18000})])
@pytest.mark.known_defect('JR-004')
def test_broken_nested_stats_preserve_previous_snapshot(tmp_path, field, value):
    events = sample_events()
    path = write_journal(tmp_path, events)
    result = read_model(tmp_path)
    damaged = deepcopy(events[3])
    damaged[field] = value
    damaged['timestamp'] = event('unused', 1)['timestamp']
    append_events(path, damaged)
    result.read_journals()
    result.update_carriers(NOW)
    assert result.get_finance(1)['CarrierBalance'] == 1_000_000_000
    assert result.get_carriers()[1]['Fuel']['FuelLevel'] == 500
    assert_tables_render(result)


def test_deleted_digit_that_remains_valid_is_used_as_written(tmp_path):
    records = sample_events()
    records[3]['Finance']['CarrierBalance'] = 100_000_000
    write_journal(tmp_path, records)
    result = read_model(tmp_path)
    assert result.get_finance(1)['CarrierBalance'] == 100_000_000


def test_missing_crew_collection_still_renders(tmp_path):
    records = sample_events()
    records[3]['Crew'] = None
    write_journal(tmp_path, records)
    result = read_model(tmp_path)
    assert result.calculate_upkeep(1) == 5_000_000


def test_deleted_event_name_character_is_ignored_and_future_records_continue(tmp_path):
    records = sample_events()
    damaged = dict(records[3], event='CarrierStat', FuelLevel=100)
    write_journal(tmp_path, records + [damaged, event('CarrierDepositFuel', 1, CarrierID=1, Total=600)])
    result = read_model(tmp_path)
    assert result.get_carriers()[1]['Fuel']['FuelLevel'] == 600
    assert len(result.journal_reader.get_items()[4]) == 1


@pytest.mark.known_defect('JR-005')
def test_partial_first_record_waits_for_completion_without_crashing(tmp_path):
    encoded = json.dumps(sample_events()[3]).encode('utf-8')
    path = write_journal(tmp_path, [])
    path.write_bytes(encoded[:20])
    reader = JournalReader([str(tmp_path)])
    reader.read_journals()
    with path.open('ab') as stream:
        stream.write(encoded[20:] + b'\n')
    reader.read_journals()
    reader.read_journals()
    assert len(reader.get_items()[4]) == 1


@pytest.mark.parametrize('name', ['Commander', 'LoadGame', 'CarrierBuy', 'CarrierLocation',
                                'SquadronStartup', 'FSDJump', 'Docked', 'Shutdown',
                                'CarrierJumpRequest', 'CarrierJumpCancelled',
                                'CarrierDepositFuel', 'CarrierDockingPermission', 'Undocked'])
def test_omitted_event_category_still_renders_all_tables(tmp_path, name):
    records = sample_events() + [event('CarrierDepositFuel', -40, CarrierID=1, Total=600),
                                event('CarrierDockingPermission', -39, CarrierID=1,
                                      DockingAccess='friends', AllowNotorious=False),
                                event('Undocked', -38, StationName='ABC-123', MarketID=1),
                                event('Shutdown')]
    # Jump and cancel are both supplied so either half may be absent.
    records[-1:-1] = [event('CarrierJumpRequest', -30, CarrierID=1, SystemName='Achenar',
                                Body='Achenar', BodyID=0, DepartureTime=event('unused', 900)['timestamp']),
                      event('CarrierJumpCancelled', -20, CarrierID=1)]
    write_journal(tmp_path, [record for record in records if record['event'] != name])
    result = read_model(tmp_path)
    assert result.get_name(1) == 'Test Carrier'
    assert result.get_trade_history(1)['Commodity'].tolist() == ['Tritium']
    if name == 'Commander':
        assert result.get_owned_carrier('F1') is None
    if name == 'LoadGame':
        assert result.get_finance(1)['CmdrBalance'] is None


@pytest.mark.parametrize('omitted', range(7))
def test_missing_single_incremental_event_keeps_other_updates_usable(tmp_path, omitted):
    records = sample_events()
    path = write_journal(tmp_path, records)
    result = read_model(tmp_path)
    updates = [event('LoadGame', 1, FID='F1', Commander='Commander F1', Credits=3000000000),
               dict(records[3], timestamp=event('unused', 2)['timestamp'], FuelLevel=510),
               event('CarrierDepositFuel', 3, CarrierID=1, Total=800),
               event('CarrierLocation', 4, CarrierID=1, StarSystem='Achenar', BodyID=0),
               event('CarrierDockingPermission', 5, CarrierID=1, DockingAccess='friends', AllowNotorious=True),
               event('Undocked', 6, StationName='ABC-123', MarketID=1),
               event('FSDJump', 7, StarSystem='Achenar')]
    append_events(path, *(record for index, record in enumerate(updates) if index != omitted))
    for _ in range(2):
        result.read_journals()
    assert_tables_render(result)
    assert result.get_carriers()[1]['Fuel']['FuelLevel'] == (510 if omitted == 2 else 800)
    assert result.get_current_system(1) == ('Sol' if omitted == 3 else 'Achenar')
    assert len(result.journal_reader.get_items()[4]) == (1 if omitted == 1 else 2)
    assert result.get_trade_history(1)['Commodity'].tolist() == ['Tritium']


@pytest.mark.parametrize('omitted', [0, 1, 2])
def test_one_of_repeated_stats_lines_can_be_missing(tmp_path, omitted):
    records = sample_events()
    stats = [dict(records[3], timestamp=event('unused', i)['timestamp'], FuelLevel=500+i*100)
             for i in range(3)]
    write_journal(tmp_path, [r for r in records if r['event'] != 'CarrierStats']
                  + [record for index, record in enumerate(stats) if index != omitted])
    result = read_model(tmp_path)
    assert result.get_carriers()[1]['Fuel']['FuelLevel'] == (600 if omitted == 2 else 700)


@pytest.mark.parametrize('stage', ['initial', 'incremental'])
@pytest.mark.known_defect('JR-005')
def test_missing_stats_recovers_when_stats_event_arrives(tmp_path, stage):
    records = sample_events()
    path = write_journal(tmp_path, [r for r in records if r['event'] != 'CarrierStats'])
    if stage == 'initial':
        result = CarrierModel([str(tmp_path)])
    else:
        reader = JournalReader([str(tmp_path)])
        reader.read_journals()
    append_events(path, records[3])
    if stage == 'incremental':
        result = CarrierModel([str(tmp_path)], journal_reader=reader)
    result.read_journals()
    assert_tables_render(result)
    assert result.get_name(1) == 'Test Carrier'


@pytest.mark.parametrize('kind', ['empty', 'missing', 'healthy_and_missing', 'healthy_and_empty'])
@pytest.mark.known_defect('JR-006')
def test_unavailable_journal_directory_recovers_when_file_arrives(tmp_path, kind):
    absent = tmp_path / 'absent'
    healthy = tmp_path / 'healthy'
    paths = [str(absent)]
    if 'empty' in kind:
        absent.mkdir()
    if kind.startswith('healthy'):
        write_journal(healthy, sample_events())
        paths.insert(0, str(healthy))
    reader = JournalReader(paths)
    reader.read_journals()
    if kind.startswith('healthy'):
        assert len(reader.get_items()[4]) == 1
    write_journal(absent, sample_events(fid='F2', carrier_id=2, callsign='DEF-456'))
    reader.read_journals()
    result = CarrierModel(paths, journal_reader=reader)
    assert result.get_owned_carrier('F2') == 2
    assert_tables_render(result)


@pytest.mark.known_defect('JR-006')
def test_disappearing_file_does_not_block_healthy_journal(tmp_path, monkeypatch):
    import model
    healthy = write_journal(tmp_path, sample_events())
    vanished = 'Journal.2026-01-02T120001.01.log'
    monkeypatch.setattr(model, 'listdir', lambda _: [healthy.name, vanished])
    result = CarrierModel([str(tmp_path)])
    assert result.get_name(1) == 'Test Carrier'
    assert_tables_render(result)


def test_account_without_a_new_session_keeps_historical_data(tmp_path):
    write_journal(tmp_path, sample_events() + [event('Shutdown')], 'Journal.2026-01-01T120000.01.log')
    write_journal(tmp_path, sample_events(fid='F2', carrier_id=2, name='Second', callsign='DEF-456'))
    result = read_model(tmp_path)
    assert set(result.get_carriers()) == {1, 2}
    assert result.get_owned_carrier('F1') == 1
    assert result.journal_reader.get_latest_active_journals().keys() == {'F2'}


def test_mixed_initial_accounts_keep_ids_but_do_not_guess_ownership(tmp_path):
    first = sample_events()
    second = sample_events(fid='F2', carrier_id=2, name='Second', callsign='DEF-456')
    interleaved = [item for pair in zip(first, second) for item in pair]
    write_journal(tmp_path, interleaved)
    result = read_model(tmp_path)
    assert set(result.get_carriers()) == {1, 2}
    assert result.get_owned_carrier('F1') is None
    assert result.get_owned_carrier('F2') is None
    assert result.get_cmdr_current_location('F1') == (None, None)
    for _ in range(3):
        result.read_journals()
    assert len(result.journal_reader.get_items()[4]) == 2


@pytest.mark.known_defect('JR-007')
def test_interleaved_append_batches_preserve_established_owners(tmp_path):
    # Establish owners from independent files before a shared file appears.
    write_journal(tmp_path, sample_events() + [event('Shutdown')], 'Journal.2026-01-01T110000.01.log')
    write_journal(tmp_path, sample_events(fid='F2', carrier_id=2, callsign='DEF-456') + [event('Shutdown')],
                  'Journal.2026-01-01T120000.01.log')
    shared = write_journal(tmp_path, [event('Commander', FID='F1')])
    result = read_model(tmp_path)
    second_stats = sample_events(fid='F2', carrier_id=2, callsign='DEF-456')[3]
    append_events(shared, second_stats)  # No reliable identity for this instance's record.
    result.read_journals()
    assert result.get_owned_carrier('F2') == 2
    assert result.carrier_owners == {1: 'F1', 2: 'F2'}


@pytest.mark.known_defect('JR-008')
def test_switching_accounts_in_shared_file_does_not_duplicate_consumption(tmp_path):
    shared = write_journal(tmp_path, sample_events())
    result = read_model(tmp_path)
    second = sample_events(fid='F2', carrier_id=2, callsign='DEF-456')
    append_events(shared, *second)
    result.read_journals()
    result.update_carriers(NOW)
    for _ in range(3):
        result.read_journals()
    assert len(result.journal_reader.get_items()[4]) == 2
    assert len(result.journal_reader.get_items()[0]) == 2
    assert_tables_render(result)


@pytest.mark.known_defect('JR-009')
def test_one_instance_shutdown_does_not_hide_other_instance_appends(tmp_path):
    records = sample_events() + [event('Commander', FID='F1'), event('Shutdown')]
    shared = write_journal(tmp_path, records)
    result = read_model(tmp_path)
    append_events(shared, event('CarrierDepositFuel', 1, CarrierID=1, Total=777))
    result.read_journals()
    result.update_carriers(NOW)
    assert result.get_carriers()[1]['Fuel']['FuelLevel'] == 777


def test_same_account_multiple_instances_without_shutdown_are_consumed_once(tmp_path):
    records = sample_events() + [event('Commander', FID='F1'),
                                event('CarrierDepositFuel', CarrierID=1, Total=777)]
    shared = write_journal(tmp_path, records)
    result = read_model(tmp_path)
    result.journal_reader = pickle.loads(pickle.dumps(result.journal_reader))
    append_events(shared, event('CarrierDepositFuel', 1, CarrierID=1, Total=800))
    for _ in range(3):
        result.read_journals()
    result.update_carriers(NOW)
    assert result.get_carriers()[1]['Fuel']['FuelLevel'] == 800
    assert len(result.journal_reader.get_items()[7]) == 2


@pytest.mark.known_defect('JR-010')
def test_missing_commander_in_older_running_journal_still_accepts_carrier_updates(tmp_path):
    records = [record for record in sample_events() if record['event'] != 'Commander']
    path = write_journal(tmp_path, records, 'Journal.2026-01-01T100000.01.log')
    result = read_model(tmp_path)
    append_events(path, event('CarrierDepositFuel', 1, CarrierID=1, Total=800))
    result.read_journals()
    result.update_carriers(NOW)
    assert result.get_owned_carrier('F1') is None
    assert result.get_carriers()[1]['Fuel']['FuelLevel'] == 800
