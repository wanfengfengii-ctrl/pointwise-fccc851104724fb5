from lake import Archive, Custodian, CustodyState, PartCommitment, PartSource, Receiving, ReportSource, initialize
from lake.custody.basis import BasisObligations

from tests.support import DAY, HEAD, TAIL, Interrupted, LakeTestCase


class RetirementTests(LakeTestCase):
    def test_expiry_orders_admission(self):
        parent = self.issue()
        original = self.submit(parent)
        self.assertEqual(self.keeper.expire_edition(parent), CustodyState.EXPIRED)
        self.assert_code('expired', self.archive.read_edition, parent)
        new = self.issue(tail=50, batch_id='later', issue_id='second')
        self.assertEqual(self.archive.current_edition(DAY).edition_id, new)
        self.archive.close()
        opened = Receiving(self.directory)
        self.assert_code('expired', self.submit, parent, identifier='B', receiving=opened)
        self.assert_unpublished('B')
        self.assertEqual(self.submit(parent, receiving=opened), original)
        self.assertEqual(self.submit(parent, 'night', TAIL, receiving=opened).missing, ())
        result = opened.finish_supplement('A')
        values = [line.litres for line in result.ledger.lines]
        self.assertEqual((values, result.ledger.totals.litres), ([8, 13, 5], 26),
                         'WRONG_DELTA_BASE after expiry and the same-day later issue')
        self.assertEqual(result.ledger.parent_id, parent)
        self.assertEqual(result.ledger.lines[2].source, ReportSource('morning', 'tail', '尾闸'))
        self.assertEqual(self.persisted_receipts(), 1)

    def test_staged_then_expired(self):
        parent = self.issue()
        reached = []

        def expire_at_stage(phase, identifier):
            reached.append(phase)
            if phase == 'first_staged':
                self.assertEqual(self.receipt_state(identifier), ('staged', ()))
                self.assertEqual([row.litres for row in self.archive.read_edition(parent).rows], [7, 11, 5])
                with self.custody_db.transaction() as conn:
                    self.assertIsNone(BasisObligations(conn).find(identifier))
                self.assertEqual(Custodian(self.directory).expire_edition(parent), CustodyState.EXPIRED)
                raise Interrupted('receiving stopped before custody admission')

        with self.assertRaises(Interrupted):
            self.submit(parent, receiving=Receiving(self.directory, checkpoint=expire_at_stage))
        self.assertEqual(reached, ['first_staged'])
        reopened = Receiving(self.directory)
        self.assert_code('expired', self.submit, parent, receiving=reopened)
        self.assert_code('not_admitted', reopened.finish_supplement, 'A')
        self.assertEqual(self.receipt_state(), ('rejected', ()))
        self.assert_unpublished()
        self.assertEqual(self.keeper.reclaim_edition(parent), 'reclaimed')

    def test_custody_admission_survives_lost_reply(self):
        parent = self.issue()

        def expire_after_authorization(phase, identifier):
            if phase == 'first_authorized':
                self.assertEqual(self.receipt_state(identifier), ('staged', ()))
                with self.custody_db.transaction() as conn:
                    obligation = BasisObligations(conn).find(identifier)
                self.assertEqual(obligation.edition_id, parent)
                self.assertEqual(Custodian(self.directory).expire_edition(parent), CustodyState.EXPIRED)
                raise Interrupted('custody admitted the first part before the reply was lost')

        sender = Receiving(self.directory, checkpoint=expire_after_authorization)
        with self.assertRaises(Interrupted):
            self.submit(parent, receiving=sender)
        newer = self.issue(tail=50, batch_id='later', issue_id='second')
        self.assertNotEqual(newer, parent)
        self.assertEqual(self.keeper.reclaim_edition(parent), 'pending')
        self.archive.close()
        opened = Receiving(self.directory)
        self.assertEqual(self.submit(parent, 'night', TAIL, receiving=opened).missing, ())
        delivery = opened.finish_supplement('A')
        self.assertEqual([row.litres for row in delivery.ledger.lines], [8, 13, 5])
        self.assertEqual(delivery.ledger.lines[0].source, PartSource('A', 'white', 0))
        self.assertEqual(self.submit(parent, receiving=opened).missing, ('night',))
        self.assertEqual(self.keeper.reclaim_edition(parent), 'reclaimed')

    def test_finish_recovers_a_single_authorized_part(self):
        parent = self.issue()

        def lose_reply(phase, identifier):
            if phase == 'first_authorized':
                raise Interrupted(identifier)

        with self.assertRaises(Interrupted):
            self.submit(parent, receiving=Receiving(self.directory, checkpoint=lose_reply),
                        commitment=PartCommitment(('white',)))
        self.keeper.expire_edition(parent)
        self.archive.close()
        result = Receiving(self.directory).finish_supplement('A')
        self.assertEqual([line.litres for line in result.ledger.lines], [8, 11, 5])
        self.assertEqual(result.ledger.totals.litres, 24)
        self.assertEqual(self.persisted_receipts(), 1)

    def test_reclaim_preserves_basis(self):
        parent = self.issue()
        self.submit(parent)
        self.keeper.expire_edition(parent)
        self.assertEqual(self.keeper.reclaim_edition(parent), 'pending')
        self.assertEqual([row.litres for row in self.physical_rows(parent)], [7, 11, 5])
        self.archive.close()
        reopened = Receiving(self.directory)
        self.submit(parent, 'night', TAIL, receiving=reopened)
        self.assertEqual(reopened.finish_supplement('A').ledger.totals.litres, 26)
        self.assertEqual(self.keeper.reclaim_edition(parent), 'reclaimed')
        self.assertEqual(self.physical_rows(parent), ())

    def test_reclaim_then_read(self):
        parent = self.issue()
        self.submit(parent)
        self.submit(parent, 'night', TAIL)
        fixed = self.receiving.finish_supplement('A')
        self.keeper.expire_edition(parent)
        self.assertEqual(self.keeper.reclaim_edition(parent), 'reclaimed')
        self.assertEqual(self.physical_rows(parent), ())
        self.archive.close()
        reopened = Receiving(self.directory)
        self.assertEqual(reopened.read_ledger('A'), fixed)
        self.assertEqual(reopened.finish_supplement('A'), fixed)
        self.assertEqual([row.litres for row in fixed.ledger.lines], [8, 13, 5])
        self.assertEqual(fixed.ledger.lines[2].source, ReportSource('morning', 'tail', '尾闸'))
        self.assertEqual(fixed.ledger.totals.litres, 26)
        self.assertEqual(self.persisted_receipts(), 1)

    def test_reclaim_boundary(self):
        parent = self.issue()
        self.assert_code('unknown_edition', self.keeper.expire_edition, 'absent')
        self.assertEqual(self.keeper.custody_state(parent), CustodyState.OPEN)
        self.assert_code('not_expired', self.keeper.reclaim_edition, parent)
        self.submit(parent, identifier='A')
        self.submit(parent, identifier='B')
        self.keeper.expire_edition(parent)
        self.assertEqual(self.keeper.expire_edition(parent), CustodyState.EXPIRED)
        self.submit(parent, 'night', TAIL, identifier='A')
        self.receiving.finish_supplement('A')
        self.assertEqual(self.keeper.reclaim_edition(parent), 'pending')
        with self.custody_db.transaction() as conn:
            active = BasisObligations(conn).outstanding(parent)
        self.assertEqual([item.supplement_id for item in active], ['B'])
        self.submit(parent, 'night', TAIL, identifier='B')
        self.receiving.finish_supplement('B')
        self.assertEqual(self.keeper.reclaim_edition(parent), 'reclaimed')
        self.assertEqual(self.keeper.reclaim_edition(parent), 'reclaimed')
        self.assertEqual(self.keeper.expire_edition(parent), CustodyState.EXPIRED)
        self.assertEqual(self.keeper.custody_state(parent), CustodyState.RECLAIMED)
        self.assertEqual(self.physical_rows(parent), ())

    def test_reinitialize(self):
        parent = self.issue()
        initial_manifest = self.archive.current_edition(DAY)
        white = self.submit(parent)
        initialize(self.directory)
        opened = Receiving(self.directory)
        self.assertEqual(self.submit(parent, receiving=opened), white)
        self.assert_code('conflict', self.submit, parent, replacements=TAIL, receiving=opened)
        self.submit(parent, 'night', TAIL, receiving=opened)
        delivery = opened.finish_supplement('A')
        self.keeper.expire_edition(parent)
        self.keeper.reclaim_edition(parent)
        self.archive.close()
        initialize(self.directory)
        self.assertEqual(Custodian(self.directory).custody_state(parent), CustodyState.RECLAIMED)
        self.assertEqual(Archive(self.directory).freeze_edition(DAY, 'morning', 'first'), initial_manifest)
        self.assertEqual(self.physical_rows(parent), ())
        self.assertEqual(Receiving(self.directory).read_ledger('A'), delivery)
        self.assertEqual(self.persisted_receipts(), 1)
