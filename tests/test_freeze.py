from lake import Archive, RawRecord, ReportSource, initialize

from tests.support import DAY, LakeTestCase


class FreezeTests(LakeTestCase):
    def test_normalization_and_missingness(self):
        batch = self.archive.ingest('intake', (
            RawRecord('a', '北堤', 7000, 'mL'),
            RawRecord('b', '南堤', None, 'mL', True),
            RawRecord('c', '尾闸', 11, 'L'),
        ))
        self.assertEqual((batch.valid_litres, batch.missing_count), ((7, 11), 1))
        manifest = self.archive.freeze_edition(DAY, 'intake', 'freeze')
        edition = self.archive.read_edition(manifest.edition_id)
        self.assertEqual(edition.manifest, manifest)
        self.assertEqual((manifest.row_count, manifest.missing_count), (3, 1))
        self.assertEqual([row.position for row in edition.rows], [0, 1, 2])
        self.assertEqual([row.litres for row in edition.rows], [7, None, 11])
        self.assertEqual([row.missing for row in edition.rows], [False, True, False])
        self.assertEqual([row.source for row in edition.rows], [
            ReportSource('intake', 'a', '北堤'), ReportSource('intake', 'b', '南堤'), ReportSource('intake', 'c', '尾闸'),
        ])

    def test_reject_fractional_litre(self):
        for value, unit, code in ((7500, 'mL', 'fractional_litre'), (-7500, 'mL', 'fractional_litre'),
                                  (7, 'gal', 'invalid_unit'), (True, 'L', 'invalid_record')):
            with self.subTest(value=value, unit=unit):
                self.assert_code(code, self.archive.ingest, 'bad', (
                    RawRecord('ok', '北堤', 11, 'L'), RawRecord('bad', '尾闸', value, unit),
                ))
                self.assert_code('unknown_batch', self.archive.freeze_edition, DAY, 'bad', 'bad-issue')
                self.assertIsNone(self.archive.current_edition(DAY))

    def test_edition_identity(self):
        old_id = self.issue()
        old = self.archive.read_edition(old_id)
        self.assertEqual(self.archive.freeze_edition(DAY, 'morning', 'first'), old.manifest)
        new_id = self.issue(tail=50, batch_id='later', issue_id='second')
        self.assertNotEqual(new_id, old_id)
        self.assertEqual(self.archive.current_edition(DAY).edition_id, new_id)
        self.assertEqual(self.archive.read_edition(old_id), old)
        new = self.archive.read_edition(new_id)
        self.assertEqual([row.litres for row in new.rows], [7, 11, 50])
        self.assertNotEqual(new.manifest.digest, old.manifest.digest)

    def test_batch_replay(self):
        initial = (RawRecord('a', '北堤', 7000, 'mL'), RawRecord('b', '尾闸', 0, 'L'))
        issued = self.archive.ingest('reported', initial)
        initialize(self.directory)
        opened = Archive(self.directory)
        self.assertEqual(opened.ingest('reported', initial), issued)
        self.assert_code('conflict', opened.ingest, 'reported', (RawRecord('a', '北堤', 7, 'L'), initial[1]))
        self.assert_code('conflict', opened.ingest, 'reported', tuple(reversed(initial)))
        manifest = opened.freeze_edition(DAY, 'reported', 'issue')
        self.assertEqual([row.litres for row in opened.read_edition(manifest.edition_id).rows], [7, 0])
        self.assertEqual(opened.ingest('reported', initial).raw_records, initial)

    def test_duplicate_row(self):
        self.assert_code('duplicate_record', self.archive.ingest, 'same-id', (
            RawRecord('r', '北堤', 11, 'L'), RawRecord('r', '尾闸', None, 'L', True),
        ))
        self.assert_code('unknown_batch', self.archive.freeze_edition, DAY, 'same-id', 'try')

    def test_issue_reject(self):
        self.assert_code('unknown_batch', self.archive.freeze_edition, DAY, 'absent', 'first')
        first = self.issue()
        self.archive.ingest('second-batch', (RawRecord('only', '南堤', 91, 'L'),))
        self.assert_code('conflict', self.archive.freeze_edition, DAY, 'second-batch', 'first')
        self.assert_code('conflict', self.archive.freeze_edition, '2026-10-13', 'morning', 'first')
        self.assertIsNone(self.archive.current_edition('2026-10-13'))
        self.assertEqual(self.archive.current_edition(DAY).edition_id, first)
        self.assertEqual(self.archive.freeze_edition(DAY, 'second-batch', 'second').edition_id, f'{DAY}#2')

    def test_manifest_depends_on_row_order(self):
        records = (RawRecord('x', '北堤', 7, 'L'), RawRecord('y', '尾闸', 7, 'L'))
        self.archive.ingest('same-reading', records)
        manifest = self.archive.freeze_edition(DAY, 'same-reading', 'order')
        evidence = self.archive.read_edition(manifest.edition_id)
        self.assertEqual([row.source.record_id for row in evidence.rows], ['x', 'y'])
        # Swapping just the persisted origins changes the ordered evidence even when readings are equal.
        with self.custody_db.transaction(write=True) as conn:
            conn.execute('''
                UPDATE frozen_rows SET record_id = CASE position WHEN 0 THEN 'y' ELSE 'x' END
                WHERE edition_id = ?
            ''', (manifest.edition_id,))
        self.assert_code('basis_unavailable', self.archive.read_edition, manifest.edition_id)
