"""Regressions for the inter-shift handover incident described in INCIDENT.md."""

from lake import Custodian, CustodyState, PartSource, Receiving, ReportSource

from tests.support import DAY, HEAD, TAIL, Interrupted, LakeTestCase


class ShiftHandoverTests(LakeTestCase):
    def test_expiry_after_admission_keeps_exact_parent_for_remaining_parts(self):
        """Expiry lands after formal admission: the lost reply must not lose the basis."""
        parent = self.issue()

        def lose_reply(phase, identifier):
            if phase == 'first_authorized':
                raise Interrupted('the first-part reply did not arrive')

        with self.assertRaises(Interrupted):
            self.submit(parent, receiving=Receiving(self.directory, checkpoint=lose_reply))
        # Only the staged row is visible locally; formal admission already lives in custody.
        self.assertEqual(self.receipt_state(), ('staged', ()))
        self.assertEqual(self.keeper.expire_edition(parent), CustodyState.EXPIRED)
        newer = self.issue(tail=50, batch_id='later', issue_id='second')
        self.assertNotEqual(newer, parent)
        self.archive.close()

        # A newer same-day edition is never accepted in place of the committed parent.
        self.assert_code('conflict', self.submit, newer, 'night', TAIL)
        self.assert_code('expired', self.submit, parent, identifier='B', receiving=Receiving(self.directory))
        self.assert_unpublished('B')

        reopened = Receiving(self.directory)
        self.assertEqual(self.submit(parent, 'night', TAIL, receiving=reopened).missing, ())
        delivery = reopened.finish_supplement('A')
        values = [line.litres for line in delivery.ledger.lines]
        self.assertEqual((values, delivery.ledger.totals.litres), ([8, 13, 5], 26))
        self.assertEqual(delivery.ledger.parent_id, parent)
        self.assertEqual([line.source for line in delivery.ledger.lines], [
            PartSource('A', 'white', 0), PartSource('A', 'night', 1),
            ReportSource('morning', 'tail', '尾闸'),
        ])
        self.assertEqual(self.keeper.reclaim_edition(parent), 'reclaimed')
        self.assertEqual(self.persisted_receipts(), 1)
        self.assertEqual(Receiving(self.directory).read_ledger('A'), delivery)

    def test_staged_only_never_earns_a_later_basis(self):
        """Staging alone cannot qualify, even after the day's later edition exists."""
        parent = self.issue()

        def stop_before_admission(phase, identifier):
            if phase == 'first_staged':
                raise Interrupted('paused between staging and admission')

        with self.assertRaises(Interrupted):
            self.submit(parent, receiving=Receiving(self.directory, checkpoint=stop_before_admission))
        self.assertEqual(self.receipt_state(), ('staged', ()))
        self.keeper.expire_edition(parent)
        self.issue(tail=50, batch_id='later', issue_id='second')
        self.archive.close()
        reopened = Receiving(self.directory)
        self.assert_code('expired', self.submit, parent, receiving=reopened)
        self.assert_code('not_admitted', reopened.finish_supplement, 'A')
        self.assertEqual(self.receipt_state(), ('rejected', ()))
        self.assert_unpublished()
        self.assertEqual(self.keeper.reclaim_edition(parent), 'reclaimed')

    def test_second_part_cannot_precede_first_admission(self):
        parent = self.issue()

        def stop_before_admission(phase, identifier):
            if phase == 'first_staged':
                raise Interrupted('paused between staging and admission')

        with self.assertRaises(Interrupted):
            self.submit(parent, receiving=Receiving(self.directory, checkpoint=stop_before_admission))
        self.assert_code('pending_first', self.submit, parent, 'night', TAIL)
        self.assertEqual(self.receipt_state(), ('staged', ()))
        self.assert_code('not_admitted', Receiving(self.directory).finish_supplement, 'A')
        self.assert_unpublished()

    def test_reclaim_stays_pending_until_every_obligation_releases(self):
        parent = self.issue()
        self.submit(parent, identifier='A')
        self.submit(parent, identifier='B')
        self.keeper.expire_edition(parent)
        self.assertEqual(self.keeper.reclaim_edition(parent), 'pending')
        self.assertEqual(self.keeper.reclaim_edition(parent), 'pending')
        self.assertNotEqual(self.physical_rows(parent), ())

        self.submit(parent, 'night', TAIL, identifier='A')
        self.receiving.finish_supplement('A')
        self.assertEqual(self.keeper.reclaim_edition(parent), 'pending')
        self.assertNotEqual(self.physical_rows(parent), ())

        self.submit(parent, 'night', TAIL, identifier='B')
        self.receiving.finish_supplement('B')
        self.assertEqual(self.keeper.reclaim_edition(parent), 'reclaimed')
        self.assertEqual(self.physical_rows(parent), ())
        self.assertEqual(self.keeper.reclaim_edition(parent), 'reclaimed')
        self.assertNotEqual(Receiving(self.directory).read_ledger('A'), None)

    def test_same_terms_continue_and_recollect_after_restart(self):
        parent = self.issue()
        white = self.submit(parent)
        night = self.submit(parent, 'night', TAIL)
        fixed = self.receiving.finish_supplement('A')
        self.keeper.expire_edition(parent)
        self.assertEqual(self.keeper.reclaim_edition(parent), 'reclaimed')
        self.archive.close()

        reopened = Receiving(self.directory)
        self.assertEqual(self.submit(parent, receiving=reopened), white)
        self.assertEqual(self.submit(parent, 'night', TAIL, receiving=reopened), night)
        self.assertEqual(reopened.read_ledger('A'), fixed)
        self.assertEqual(reopened.finish_supplement('A'), fixed)
        self.assert_code('conflict', self.submit, parent, 'night', (HEAD[0],), receiving=reopened)
        self.assert_code('conflict', self.submit, 'another-edition', receiving=reopened)
        self.assertEqual(self.persisted_receipts(), 1)
