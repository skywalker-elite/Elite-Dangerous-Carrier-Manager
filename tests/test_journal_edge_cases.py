import json
import pickle
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from model import JournalReader, CarrierModel


class JournalEdgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = Path(self.tmp.name) / 'Journal.2020-01-01T000000.01.log'
        self.reader = JournalReader([self.tmp.name])

    def event(self, name, **fields):
        return json.dumps(dict(event=name, timestamp='2020-01-01T00:00:00Z', **fields),
                          ensure_ascii=False).encode('utf-8')

    def append(self, data, file=None):
        with (file or self.file).open('ab') as stream:
            stream.write(data)

    def seed(self):
        self.append(self.event('Commander', FID='F1') + b'\n'
                    + self.event('CarrierStats', CarrierID=1) + b'\n')

    def test_partial_then_complete_with_pickle_and_no_duplicates(self):
        for newline in (b'\n', b'\r\n'):
            with self.subTest(newline=newline):
                self.file.write_bytes(b'')
                self.reader = JournalReader([self.tmp.name])
                self.seed()
                event = self.event('CarrierJumpRequest', SystemName='Sol')
                self.append(event[:20])
                self.reader.read_journals()
                self.reader.get_items()
                self.reader.update_items_count()
                offset = self.reader._journal_pending[str(self.file)]['byte_pos']
                self.reader.read_journals()
                self.assertEqual(len(self.reader._stats), 1)
                self.assertEqual(self.reader._jump_requests, [])
                self.reader = pickle.loads(pickle.dumps(self.reader))
                self.append(event[20:] + newline)
                self.reader.read_journals()
                self.reader.read_journals()
                self.assertEqual(len(self.reader.get_new_items()[2]), 1)
                self.assertEqual(len(self.reader._stats), 1)
                self.assertFalse(self.reader._journal_pending)
                self.assertGreater(self.reader.journal_latest['F1']['byte_pos'], offset)
                self.assertIsInstance(self.reader.journal_processed, set)

    def test_valid_json_waits_for_newline(self):
        self.seed()
        self.reader.read_journals()
        self.append(self.event('CarrierJumpRequest'))
        self.reader.read_journals()
        self.assertFalse(self.reader._jump_requests)
        self.append(b'\n')
        self.reader.read_journals()
        self.assertEqual(len(self.reader._jump_requests), 1)

    def test_split_utf8(self):
        self.seed()
        event = self.event('CarrierJumpRequest', SystemName='Café')
        split = event.index('é'.encode()) + 1
        self.append(event[:split])
        self.reader.read_journals()
        self.append(event[split:] + b'\n')
        self.reader.read_journals()
        self.assertEqual(self.reader._jump_requests[0]['SystemName'], 'Café')

    def test_malformed_complete_lines_advance_without_status_change(self):
        self.seed()
        self.reader.read_journals()
        self.append(b'not JSON\n')
        with patch('builtins.print') as log:
            self.reader.read_journals()
            self.reader.read_journals()
        self.assertEqual(log.call_count, 1)
        self.assertTrue(self.reader.journal_latest['F1']['is_active'])
        self.append(b'bad JSON\n' + self.event('CarrierJumpRequest') + b'\n')
        with patch('builtins.print'):
            self.reader.read_journals()
        self.assertEqual(len(self.reader._jump_requests), 1)

    def test_old_tail_does_not_replace_new_active_journal(self):
        self.seed()
        shutdown = self.event('Shutdown')
        self.append(shutdown[:10])
        self.reader.read_journals()
        newer = self.file.with_name('Journal.2020-01-02T000000.01.log')
        self.append(self.event('Commander', FID='F1') + b'\n', newer)
        self.reader.read_journals()
        self.assertNotIn(str(self.file), self.reader._journal_pending)
        self.append(shutdown[10:] + b'\n')
        self.reader.read_journals()
        self.assertEqual(self.reader.journal_latest['F1']['filename'], str(newer))
        self.assertTrue(self.reader.journal_latest['F1']['is_active'])
        self.append(self.event('CarrierJumpRequest') + b'\n', newer)
        self.reader.read_journals()
        self.assertEqual(len(self.reader._jump_requests), 1)

    def test_retired_tail_cannot_overwrite_newer_balance(self):
        self.seed()
        old = self.event('LoadGame', FID='F1', Commander='Test', Credits=100)
        self.append(old[:20])
        self.reader.read_journals()
        self.reader.get_items()
        self.reader.update_items_count()
        newer = self.file.with_name('Journal.2020-01-02T000000.01.log')
        self.append(self.event('Commander', FID='F1') + b'\n'
                    + self.event('LoadGame', FID='F1', Commander='Test', Credits=200) + b'\n', newer)
        self.reader.read_journals()
        model = CarrierModel.__new__(CarrierModel)
        model.cmdr_balances = {}
        model.cmdr_names = {}
        model._load_game_times = {}
        model.process_load_games(self.reader.get_new_items()[0], first_read=False)
        self.reader.update_items_count()
        self.assertNotIn(str(self.file), self.reader._journal_pending)
        self.reader = pickle.loads(pickle.dumps(self.reader))
        self.append(old[20:] + b'\n')
        self.reader.read_journals()
        model.process_load_games(self.reader.get_new_items()[0], first_read=False)
        self.assertEqual(model.cmdr_balances['F1'], 200)
        self.assertEqual(len(self.reader._load_games), 1)

    def test_retirement_waits_for_same_fid(self):
        self.seed()
        self.append(self.event('CarrierJumpRequest')[:20])
        self.reader.read_journals()
        newer = self.file.with_name('Journal.2020-01-02T000000.01.log')
        commander = self.event('Commander', FID='F1')
        self.append(self.event('Fileheader') + b'\n' + commander[:10], newer)
        different = self.file.with_name('Journal.2020-01-03T000000.01.log')
        self.append(self.event('Commander', FID='F2') + b'\n', different)
        self.reader.read_journals()
        self.assertIn(str(self.file), self.reader._journal_pending)
        self.append(commander[10:] + b'\n', newer)
        self.reader.read_journals()
        self.assertNotIn(str(self.file), self.reader._journal_pending)

    def test_next_write_can_create_another_pending_tail(self):
        self.seed()
        event = self.event('CarrierJumpRequest')
        self.append(event[:20])
        self.reader.read_journals()
        first_offset = self.reader._journal_pending[str(self.file)]['byte_pos']
        self.append(event[20:] + b'\n' + event[:25])
        self.reader.read_journals()
        self.assertEqual(len(self.reader._jump_requests), 1)
        self.assertGreater(self.reader._journal_pending[str(self.file)]['byte_pos'], first_offset)
        self.append(event[25:] + b'\n')
        self.reader.read_journals()
        self.assertEqual(len(self.reader._jump_requests), 2)
        self.assertNotIn(str(self.file), self.reader._journal_pending)

    def test_unknown_expired_fid_tail_is_retried(self):
        self.append(self.event('CarrierStats', CarrierID=1) + b'\n')
        commander = self.event('Commander', FID='F1')
        self.append(commander[:10])
        self.reader.read_journals()
        self.assertFalse(self.reader.journal_latest_unknown_fid)
        self.append(commander[10:] + b'\n' + self.event('CarrierStats', CarrierID=2) + b'\n')
        self.reader.read_journals()
        self.reader.read_journals()
        self.assertEqual(len(self.reader._stats), 2)
        self.assertEqual(self.reader._carrier_owners[2], 'F1')

    def test_identity_revealed_in_older_first_partial_record(self):
        commander = self.event('Commander', FID='F1')
        self.append(commander[:10])
        newer = self.file.with_name('Journal.2020-01-02T000000.01.log')
        self.append(commander + b'\n' + self.event('CarrierStats', CarrierID=1) + b'\n', newer)
        self.reader.read_journals()
        self.append(commander[10:] + b'\n' + self.event('LoadGame', FID='F1', Credits=100) + b'\n')
        self.reader.read_journals()
        self.assertEqual(self.reader.journal_latest['F1']['filename'], str(newer))
        self.assertFalse(self.reader._load_games)
        self.assertNotIn(str(self.file), self.reader._journal_pending)

    def test_identity_revealed_in_newer_pending_journal(self):
        self.seed()
        self.reader.read_journals()
        newer = self.file.with_name('Journal.2020-01-02T000000.01.log')
        commander = self.event('Commander', FID='F1')
        self.append(self.event('Fileheader') + b'\n' + commander[:10], newer)
        self.reader.read_journals()
        self.append(commander[10:] + b'\n', newer)
        self.reader.read_journals()
        self.assertEqual(self.reader.journal_latest['F1']['filename'], str(newer))

    def test_partial_record_after_valid_seed(self):
        self.seed()
        event = self.event('CarrierStats', CarrierID=1)
        self.append(event[:10])
        self.reader.read_journals()
        self.append(event[10:] + b'\n')
        self.reader.read_journals()
        self.reader.read_journals()
        self.assertEqual(len(self.reader._stats), 2)

    def test_incomplete_tail_preserves_shutdown(self):
        self.seed()
        self.append(self.event('Shutdown') + b'\n' + b'{')
        self.reader.read_journals()
        before = self.reader.journal_latest['F1'].copy()
        self.reader.read_journals()
        self.assertEqual(self.reader.journal_latest['F1'], before)
        self.assertFalse(before['is_active'])

    def test_shared_file_cursor_survives_account_change_and_pickle(self):
        self.seed()
        self.reader.read_journals()
        deposit = self.event('CarrierDepositFuel', CarrierID=2, Total=800)
        self.append(self.event('Commander', FID='F2') + b'\n'
                    + self.event('CarrierStats', CarrierID=2) + b'\n' + deposit[:20])
        self.reader.read_journals()
        self.reader = pickle.loads(pickle.dumps(self.reader))
        self.append(deposit[20:] + b'\n')
        self.reader.read_journals()
        self.reader.read_journals()
        self.assertEqual(len(self.reader._stats), 2)
        self.assertEqual([event['Total'] for event in self.reader._trit_deposits], [800])
        self.assertEqual(self.reader._carrier_owners, {1: 'F1', 2: 'F2'})

    def test_mixed_appended_commanders_do_not_inherit_previous_owner(self):
        self.seed()
        self.reader.read_journals()
        self.append(self.event('Commander', FID='F1') + b'\n'
                    + self.event('Commander', FID='F2') + b'\n'
                    + self.event('CarrierStats', CarrierID=2) + b'\n')
        self.reader.read_journals()
        self.append(self.event('CarrierStats', CarrierID=3) + b'\n')
        self.reader.read_journals()
        self.assertEqual(len(self.reader._stats), 3)
        self.assertEqual(self.reader._carrier_owners, {1: 'F1'})

    def test_closed_older_file_append_preserves_newer_active_session(self):
        self.seed()
        self.append(self.event('Shutdown') + b'\n')
        self.reader.read_journals()
        newer = self.file.with_name('Journal.2020-01-02T000000.01.log')
        self.append(self.event('Commander', FID='F1') + b'\n', newer)
        self.reader.read_journals()
        self.append(self.event('CarrierDepositFuel', CarrierID=1, Total=800) + b'\n')
        self.reader.read_journals()
        self.reader.read_journals()
        self.assertEqual([event['Total'] for event in self.reader._trit_deposits], [800])
        self.assertEqual(self.reader.get_latest_active_journals(), {'F1': str(newer)})

    def test_idle_poll_does_not_reopen_completed_files(self):
        self.seed()
        self.append(self.event('Shutdown') + b'\n')
        newer = self.file.with_name('Journal.2020-01-02T000000.01.log')
        self.append(self.event('Commander', FID='F1') + b'\n', newer)
        self.reader.read_journals()
        with patch('builtins.open', side_effect=AssertionError('Unchanged file reopened')):
            self.reader.read_journals()


class TimestampTests(unittest.TestCase):
    def test_sort_matches_chronology_and_stable_ties(self):
        times = ['2024-02-29T23:59:59Z', '2023-12-31T23:59:59Z',
                 '2024-03-01T00:00:00Z', '2024-01-01T00:00:00Z',
                 '2024-02-29T23:59:59Z']
        reader = JournalReader([])
        reader._stats = [dict(timestamp=t, index=i) for i, t in enumerate(times)]
        expected = sorted(reader._stats, key=lambda x: datetime.strptime(
            x['timestamp'], '%Y-%m-%dT%H:%M:%SZ'), reverse=True)
        self.assertEqual(reader.get_items()[4], expected)
        self.assertEqual([e['timestamp'] for e in reader._stats], times)

    def test_invalid_timestamp(self):
        invalid = ['2023-02-29T00:00:00Z', '2024-13-01T00:00:00Z',
                   '2024-01-01T24:00:00Z', '2024-01-01T00:60:00Z',
                   '2024-01-01T00:00:60Z', '2024-01-01T00:00:00.1Z',
                   '2024-01-01T00:00:00+00:00', '2024-1-01T00:00:00Z',
                   '2024-01-01T00:00:00Z\n', '0000-01-01T00:00:00Z',
                   '２０２４-01-01T00:00:00Z', None, 123]
        for value in invalid:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'Invalid journal timestamp'):
                JournalReader._timestamp_key({'timestamp': value})
        with self.assertRaises(KeyError):
            JournalReader._timestamp_key({})

    def test_mutation_is_revalidated(self):
        reader = JournalReader([])
        reader._stats = [{'timestamp': '2024-01-01T00:00:00Z'}]
        result = reader.get_items()
        result[4][0]['timestamp'] = 'invalid'
        with self.assertRaises(ValueError):
            reader.get_items()


if __name__ == '__main__':
    unittest.main()
