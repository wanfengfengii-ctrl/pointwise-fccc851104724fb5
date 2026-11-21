from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from .custody.basis import BasisEvidence as BasisEvidence
from .custody.basis import BasisObligations, read_exact_basis
from .custody.catalog import CustodyCatalog, CustodyState as CustodyState
from .custody.eligibility import check_public_eligibility
from .custody.expiry import expire_edition
from .custody.reclaim import reclaim_edition
from .editions.freeze import freeze_edition, validate_day
from .editions.history import EditionHistory
from .editions.manifest import EditionManifest as EditionManifest
from .editions.manifest import ManifestStore
from .editions.rows import EditionRowStore
from .feed.batches import BatchStore, StationBatch as StationBatch
from .feed.intake import ingest
from .feed.provenance import ReportSource as ReportSource
from .feed.records import RawRecord as RawRecord
from .ledger.lookup import read_ledger
from .ledger.publication import LedgerDelivery as LedgerDelivery
from .ledger.publication import LedgerStore
from .ledger.receipts import ReceiptStore
from .receiving.admission import submit_part
from .receiving.assembly import finish_supplement
from .receiving.commitments import PartCommitment as PartCommitment
from .receiving.parts import PartReceipt as PartReceipt
from .receiving.parts import PartSource as PartSource
from .receiving.parts import PartStore, Replacement as Replacement
from .receiving.requests import RequestStore
from .storage import Checkpoint, Database, LakeError as LakeError, require_name


def initialize(directory: str | Path) -> None:
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    with Database(root / 'custody.sqlite3').transaction(write=True, create=True) as conn:
        BatchStore(conn).initialize()
        EditionHistory(conn).initialize()
        ManifestStore(conn).initialize()
        EditionRowStore(conn).initialize()
        CustodyCatalog(conn).initialize()
        BasisObligations(conn).initialize()
    with Database(root / 'receiving.sqlite3').transaction(write=True, create=True) as conn:
        RequestStore(conn).initialize()
        PartStore(conn).initialize()
        LedgerStore(conn).initialize()
        ReceiptStore(conn).initialize()


class Archive:
    def __init__(self, directory: str | Path):
        self._database = Database(Path(directory) / 'custody.sqlite3')
        self._closed = False

    def close(self) -> None:
        self._closed = True

    def _active(self) -> Database:
        if self._closed:
            raise LakeError('upstream_closed', 'The reporting and public edition service is closed')
        return self._database

    def ingest(self, batch_id: str, records: Iterable[RawRecord]) -> StationBatch:
        return ingest(self._active(), batch_id, records)

    def freeze_edition(self, day: str, batch_id: str, issue_id: str) -> EditionManifest:
        return freeze_edition(self._active(), day, batch_id, issue_id)

    def read_edition(self, edition_id: str) -> BasisEvidence:
        require_name(edition_id, 'edition ID')
        with self._active().transaction() as conn:
            check_public_eligibility(conn, edition_id)
            return read_exact_basis(conn, edition_id)

    def current_edition(self, day: str) -> EditionManifest | None:
        validate_day(day)
        with self._active().transaction() as conn:
            edition_id = EditionHistory(conn).latest_for_day(day)
            return None if edition_id is None else ManifestStore(conn).find(edition_id)


class Custodian:
    def __init__(self, directory: str | Path):
        root = Path(directory)
        self._custody = Database(root / 'custody.sqlite3')
        self._receiving = Database(root / 'receiving.sqlite3')

    def custody_state(self, edition_id: str) -> CustodyState:
        require_name(edition_id, 'edition ID')
        with self._custody.transaction() as conn:
            return CustodyCatalog(conn).state_for(edition_id)

    def expire_edition(self, edition_id: str) -> CustodyState:
        return expire_edition(self._custody, edition_id)

    def reclaim_edition(self, edition_id: str) -> str:
        return reclaim_edition(self._custody, self._receiving, edition_id)


class Receiving:
    def __init__(self, directory: str | Path, *, checkpoint: Checkpoint | None = None):
        root = Path(directory)
        self._custody = Database(root / 'custody.sqlite3')
        self._receiving = Database(root / 'receiving.sqlite3')
        self._checkpoint = checkpoint

    def submit_part(
        self, supplement_id: str, parent_id: str, commitment: PartCommitment,
        part_id: str, replacements: Iterable[Replacement],
    ) -> PartReceipt:
        return submit_part(self._custody, self._receiving, supplement_id, parent_id, commitment,
                           part_id, replacements, checkpoint=self._checkpoint)

    def finish_supplement(self, supplement_id: str) -> LedgerDelivery:
        return finish_supplement(self._custody, self._receiving, supplement_id, checkpoint=self._checkpoint)

    def read_ledger(self, supplement_id: str) -> LedgerDelivery | None:
        require_name(supplement_id, 'supplement ID')
        with self._receiving.transaction() as conn:
            return read_ledger(conn, supplement_id)
