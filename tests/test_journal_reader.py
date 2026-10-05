import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from model import JournalReader


class JournalReaderTests(unittest.TestCase):
    EVENT_TYPES = (
        'LoadGame', 'CarrierLocation', 'CarrierJumpRequest',
        'CarrierJumpCancelled', 'CarrierStats', 'CarrierTradeOrder',
        'CarrierBuy', 'CarrierDepositFuel', 'CarrierDockingPermission',
        'SquadronStartup', 'Docked', 'Undocked', 'FSDJump',
    )

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.journal_path = Path(directory.name) / 'Journal.2025-04-11T022443.01.log'
        self.reader = JournalReader([directory.name])
        self.append_events({
            'event': 'Commander', 'FID': 'F123',
            'timestamp': '2025-04-11T02:24:43Z',
        })

    def append_events(self, *events):
        with self.journal_path.open('a', encoding='utf-8') as journal:
            for event in events:
                journal.write(json.dumps(event) + '\n')

    def stats_event(self, timestamp):
        return {'event': 'CarrierStats', 'CarrierID': 123, 'timestamp': timestamp}

    def test_full_results_preserve_order_and_references(self):
        for timestamp in ('2025-04-11T02:24:44Z', '2025-04-11T02:24:45Z'):
            self.append_events(*(
                {'event': event_type, 'timestamp': timestamp, 'CarrierID': 123}
                for event_type in self.EVENT_TYPES
            ))
        self.reader.read_journals()

        items = self.reader.get_items()

        self.assertEqual(len(items), len(self.EVENT_TYPES) + 1)
        for index, event_type in enumerate(self.EVENT_TYPES):
            with self.subTest(event_type=event_type):
                self.assertEqual([event['event'] for event in items[index]],
                                 [event_type, event_type])
                self.assertEqual([event['timestamp'] for event in items[index]],
                                 ['2025-04-11T02:24:45Z', '2025-04-11T02:24:44Z'])
                stored = getattr(self.reader, '_' + self.reader.tracked_items[index])
                self.assertIs(items[index][0], stored[1])
                self.assertIs(items[index][1], stored[0])
                self.assertIsNot(items[index], stored)
        self.assertEqual(items[-1], {123: 'F123'})
        self.assertIs(items[-1], self.reader._carrier_owners)

    def test_full_results_include_appended_events(self):
        older = self.stats_event('2025-04-11T02:24:44Z')
        newer = self.stats_event('2025-04-11T02:24:45Z')
        self.append_events(older)
        self.reader.read_journals()
        previous = self.reader.get_items()

        self.append_events(newer)
        self.reader.read_journals()
        self.assertEqual(self.reader.get_items()[4], [newer, older])
        self.assertEqual(previous[4], [older])
        self.reader.read_journals()
        self.assertEqual(self.reader.get_items()[4], [newer, older])

    def test_full_results_do_not_disrupt_incremental_reads(self):
        self.append_events(self.stats_event('2025-04-11T02:24:44Z'),
                           self.stats_event('2025-04-11T02:24:45Z'))
        self.reader.read_journals()
        self.reader.get_items()
        self.reader.update_items_count()

        newer = self.stats_event('2025-04-11T02:24:46Z')
        self.append_events(newer)
        self.reader.read_journals()
        self.reader.get_items()
        items = self.reader.get_new_items()
        self.assertEqual(items[4], [newer])
        self.assertTrue(all(not group for index, group in enumerate(items[:-1])
                            if index != 4))
        self.assertEqual(items[-1], {123: 'F123'})
        self.reader.update_items_count()
        self.assertTrue(all(not group for group in self.reader.get_new_items()[:-1]))

    def test_dropout_does_not_modify_stored_data(self):
        reader = JournalReader(self.reader.journal_paths, dropout=True,
                               droplist=['stats', 'carrier_owners'])
        stats = self.stats_event('2025-04-11T02:24:44Z')
        load_game = {'event': 'LoadGame', 'timestamp': '2025-04-11T02:24:44Z'}
        self.append_events(stats, load_game)
        reader.read_journals()

        items = reader.get_items()
        self.assertEqual(items[4], [])
        self.assertEqual(items[-1], {})
        self.assertEqual(items[0], [load_game])
        self.assertEqual(reader._stats, [stats])
        self.assertEqual(reader._carrier_owners, {123: 'F123'})
        reader.update_items_count()
        self.assertTrue(all(not group for group in reader.get_new_items()[:-1]))
        reader.dropout = False
        self.assertEqual(reader.get_items()[4], [stats])
        self.assertEqual(reader.get_items()[-1], {123: 'F123'})

    def test_stats_are_not_duplicated_on_repeated_reads(self):
        self.append_events(self.stats_event('2025-04-11T02:24:44Z'))
        self.reader.read_journals()
        self.reader.read_journals()
        self.assertEqual(len(self.reader.get_items()[4]), 1)


if __name__ == '__main__':
    unittest.main()
