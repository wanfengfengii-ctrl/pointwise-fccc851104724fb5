import contextlib
import io
import json

from lake import Archive, Custodian, CustodyState, RawRecord, Receiving
from lake.__main__ import demo

from tests.support import DAY, LakeTestCase


class WorkdayTests(LakeTestCase):
    def test_workday_and_demo_replay(self):
        observed = []
        for _ in range(2):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                demo(self.directory)
            lines = output.getvalue().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertTrue(lines[0].startswith('POINTWISE_SCENARIO '))
            scenario = json.loads(lines[0].split(' ', 1)[1])
            self.assertEqual(scenario['case_id'], 'v06.original_basis')
            self.assertEqual(scenario['actual'], {'litres_by_row': [8, 13, 5], 'total_litres': 26, 'tail_source': '尾闸'})
            self.assertEqual(scenario['downstream_actual'], {
                'late_request': 'expired', 'custody': 'reclaimed', 'reopened_total': 26, 'same_first_receipt': True,
            })
            observed.append(json.loads(lines[1]))
        self.assertEqual(observed[0], observed[1])
        self.assertEqual(self.persisted_receipts(), 1)
        delivery = Receiving(self.directory).read_ledger('A')
        self.assertEqual(delivery.receipt.number, observed[0]['receipt']['number'])
        self.assertEqual(Custodian(self.directory).custody_state(delivery.ledger.parent_id), CustodyState.RECLAIMED)
        latest = Archive(self.directory).current_edition(DAY)
        self.assertEqual([row.litres for row in self.archive.read_edition(latest.edition_id).rows], [7, 11, 50])
        self.assertIsNone(self.receiving.read_ledger('B'))

    def test_demo_respects_existing_batch(self):
        original = (RawRecord('custom', '北堤实报', 9, 'L'),)
        self.archive.ingest('morning', original)
        self.assert_code('conflict', demo, self.directory)
        self.assertEqual(Archive(self.directory).ingest('morning', original).raw_records, original)
        self.assertIsNone(self.archive.current_edition(DAY))
        self.assert_unpublished()
