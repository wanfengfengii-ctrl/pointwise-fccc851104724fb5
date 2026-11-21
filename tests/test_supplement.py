from lake import PartCommitment, PartSource, RawRecord, Receiving, Replacement, ReportSource
from lake.ledger.publication import LedgerStore
from lake.ledger.receipts import ReceiptStore

from tests.support import COMMITMENT, DAY, HEAD, TAIL, Interrupted, LakeTestCase


class SupplementTests(LakeTestCase):
    def test_complete_two_part(self):
        parent = self.issue()
        self.assertEqual(self.submit(parent).missing, ('night',))
        self.assertEqual(self.submit(parent, 'night', TAIL).missing, ())
        delivery = self.receiving.finish_supplement('A')
        self.assertEqual(delivery.ledger.parent_id, parent)
        self.assertEqual([line.position for line in delivery.ledger.lines], [0, 1, 2])
        self.assertEqual([line.litres for line in delivery.ledger.lines], [8, 13, 5])
        self.assertEqual([line.source for line in delivery.ledger.lines], [
            PartSource('A', 'white', 0), PartSource('A', 'night', 1), ReportSource('morning', 'tail', '尾闸'),
        ])
        self.assertEqual(delivery.ledger.totals.litres, 26)
        self.assertEqual(delivery.ledger.totals.missing_count, 0)
        self.assertEqual(Receiving(self.directory).read_ledger('A'), delivery)
        self.assertEqual(self.persisted_receipts(), 1)

    def test_missing_part_blocks_publication(self):
        parent = self.issue()
        self.submit(parent)
        error = self.assert_code('incomplete', self.receiving.finish_supplement, 'A')
        self.assertEqual(error.missing, ('night',))
        self.assert_unpublished()
        self.submit(parent, 'night', TAIL)
        self.assertEqual(self.receiving.finish_supplement('A').ledger.totals.litres, 26)
        self.assertEqual(self.persisted_receipts(), 1)

    def test_coverage(self):
        parent = self.issue()
        first = (Replacement(0, 8), Replacement(1, 13))
        original = self.submit(parent, replacements=first)
        for position in range(2):
            with self.subTest(retry=position):
                self.assertEqual(self.submit(parent, replacements=first), original)
        self.assert_code('invalid_part', self.submit, parent, 'other', (Replacement(2, 17),))
        error = self.assert_code('incomplete', self.receiving.finish_supplement, 'A')
        self.assertEqual(error.missing, ('night',))
        self.assert_unpublished()
        self.submit(parent, 'night', (Replacement(2, 17),))
        result = self.receiving.finish_supplement('A')
        self.assertEqual([line.litres for line in result.ledger.lines], [8, 13, 17])
        self.assertEqual(result.ledger.totals.litres, 38)
        self.assertEqual(self.persisted_receipts(), 1)

    def test_coordinate_overlap(self):
        parent = self.issue()
        self.assert_code('invalid_coordinate', self.submit, parent, 'white', (Replacement(3, 99),))
        self.assert_code('invalid_coordinate', self.submit, parent, 'white', (Replacement(True, 99),))
        self.assert_code('overlap', self.submit, parent, 'white', (Replacement(0, 9), Replacement(0, 10)))
        self.assertEqual(self.receipt_state(), (None, ()))
        first = (Replacement(0, 8), Replacement(1, 13))
        original = self.submit(parent, replacements=first)
        self.assert_code('overlap', self.submit, parent, 'night', (Replacement(1, 90), Replacement(2, 17)))
        self.assert_code('invalid_coordinate', self.submit, parent, 'night', (Replacement(3, 90),))
        self.assert_code('invalid_record', self.submit, parent, 'night', (Replacement(2, False),))
        self.assertEqual(self.receipt_state(), ('admitted', ('white',)))
        self.assertEqual(self.submit(parent, replacements=first), original)
        self.assert_unpublished()
        self.submit(parent, 'night', (Replacement(2, 17),))
        result = self.receiving.finish_supplement('A')
        self.assertEqual([line.litres for line in result.ledger.lines], [8, 13, 17])
        self.assertEqual(result.ledger.lines[1].source, PartSource('A', 'white', 1))

    def test_part_replay(self):
        parent = self.issue()
        first = (Replacement(0, 8), Replacement(1, 13))
        early = self.submit(parent, replacements=first)
        late = self.submit(parent, 'night', (Replacement(2, 17),))
        opened = Receiving(self.directory)
        self.assertEqual(self.submit(parent, replacements=reversed(first), receiving=opened), early)
        self.assertEqual(self.submit(parent, 'night', (Replacement(2, 17),), receiving=opened), late)
        self.assert_code('conflict', self.submit, parent, 'night', (Replacement(2, 23),), receiving=opened)
        self.assert_code('conflict', self.submit, parent, commitment=PartCommitment(('night', 'white')))
        self.assertEqual(self.receipt_state(), ('admitted', ('night', 'white')))
        self.assertEqual(opened.finish_supplement('A').ledger.totals.litres, 38)
        self.assertEqual(self.submit(parent, replacements=first, receiving=opened), early)
        self.assertEqual(self.persisted_receipts(), 1)

    def test_missing_totals(self):
        self.archive.ingest('report', (
            RawRecord('a', '北堤', 7000, 'mL'), RawRecord('b', '尾闸', None, 'L', True),
            RawRecord('c', '南堤', 11, 'L'), RawRecord('d', '引水渠', 0, 'L'),
            RawRecord('e', '备用站', None, 'mL', True),
        ))
        parent = self.archive.freeze_edition(DAY, 'report', 'issue').edition_id
        self.submit(parent)
        self.submit(parent, 'night', (Replacement(2, 13),))
        self.receiving.finish_supplement('A')
        ledger = Receiving(self.directory).read_ledger('A').ledger
        self.assertEqual([line.litres for line in ledger.lines], [8, None, 13, 0, None])
        self.assertEqual([line.missing for line in ledger.lines], [False, True, False, False, True])
        self.assertEqual(ledger.totals.litres, 21)
        self.assertEqual((ledger.totals.missing_count, ledger.totals.missing_positions), (2, (1, 4)))
        self.assertEqual(ledger.lines[1].source, ReportSource('report', 'b', '尾闸'))
        self.assertEqual(ledger.lines[3].source, ReportSource('report', 'd', '引水渠'))
        self.assertEqual(ledger.lines[4].source, ReportSource('report', 'e', '备用站'))

    def test_lost_publication_reply(self):
        parent = self.issue()
        self.submit(parent)
        tail = self.submit(parent, 'night', TAIL)
        observed = []

        def interrupt(phase, identifier):
            if phase == 'after_publication_commit':
                observed.append(Receiving(self.directory).read_ledger(identifier))
                raise Interrupted('reply did not arrive')

        sender = Receiving(self.directory, checkpoint=interrupt)
        with self.assertRaises(Interrupted):
            sender.finish_supplement('A')
        self.assertEqual(len(observed), 1)
        self.assertIsNotNone(observed[0])
        self.keeper.expire_edition(parent)
        self.assertEqual(self.keeper.reclaim_edition(parent), 'reclaimed')
        reopened = Receiving(self.directory)
        self.assertEqual(self.submit(parent, 'night', TAIL, receiving=reopened), tail)
        self.assertEqual(reopened.finish_supplement('A'), observed[0])
        self.assertEqual(reopened.read_ledger('A'), observed[0])
        self.assert_code('conflict', self.submit, parent, 'night', (Replacement(1, 99),), receiving=reopened)
        self.assert_code('conflict', self.submit, 'another-edition', receiving=reopened)
        self.assertEqual(self.persisted_receipts(), 1)

    def test_atomic_failure(self):
        parent = self.issue()
        self.submit(parent)
        self.submit(parent, 'night', TAIL)
        self.keeper.expire_edition(parent)
        phases = []

        def interrupt(phase, identifier):
            phases.append(phase)
            if phase == 'before_publication_commit':
                self.assert_unpublished(identifier)
                self.assertEqual(self.keeper.reclaim_edition(parent), 'pending')
                raise Interrupted('publication stopped before commit')

        with self.assertRaises(Interrupted):
            Receiving(self.directory, checkpoint=interrupt).finish_supplement('A')
        self.assertEqual(phases, ['before_publication_commit'])
        self.assert_unpublished()
        self.assertEqual(self.receipt_state(), ('admitted', ('night', 'white')))
        self.assertEqual(self.keeper.reclaim_edition(parent), 'pending')
        result = Receiving(self.directory).finish_supplement('A')
        with self.receiving_db.transaction() as conn:
            self.assertEqual(LedgerStore(conn).find('A'), result.ledger)
            self.assertEqual(ReceiptStore(conn).find('A'), result.receipt)
        self.assertEqual(self.receipt_state(), ('settled', ('night', 'white')))
        self.assertEqual(self.persisted_receipts(), 1)
        self.assertEqual(self.keeper.reclaim_edition(parent), 'reclaimed')

    def test_basis_must_match_the_committed_manifest(self):
        parent = self.issue()
        self.submit(parent)
        self.submit(parent, 'night', TAIL)
        with self.custody_db.transaction(write=True) as conn:
            conn.execute('DELETE FROM frozen_rows WHERE edition_id = ? AND position = 2', (parent,))
        self.assert_code('basis_unavailable', self.receiving.finish_supplement, 'A')
        self.assert_unpublished()

    def test_exact_integer_round_trip(self):
        large = 10 ** 5000
        self.archive.ingest('large', (
            RawRecord('a', '北堤', -2000, 'mL'), RawRecord('b', '尾闸', large * 1000, 'mL'),
        ))
        parent = self.archive.freeze_edition(DAY, 'large', 'issue').edition_id
        self.assertTrue(self.archive.read_edition(parent).rows[1].litres == large)
        commitment = PartCommitment(('only',))
        first = self.submit(parent, 'only', (Replacement(0, 10 ** 4999),), commitment=commitment)
        self.assertEqual(first.missing, ())
        self.receiving.finish_supplement('A')
        ledger = Receiving(self.directory).read_ledger('A').ledger
        self.assertTrue(ledger.lines[0].litres == 10 ** 4999)
        self.assertTrue(ledger.lines[1].litres == large)
        self.assertTrue(ledger.totals.litres == 11 * 10 ** 4999)

    def test_first_part_may_follow_commitment_order(self):
        parent = self.issue()
        self.assertEqual(self.submit(parent, 'night', TAIL, commitment=COMMITMENT).missing, ('white',))
        self.assertEqual(self.submit(parent).missing, ())
        self.assertEqual(self.receiving.finish_supplement('A').ledger.totals.litres, 26)
