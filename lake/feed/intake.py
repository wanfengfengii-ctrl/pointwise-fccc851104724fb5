from collections.abc import Iterable

from lake.feed.batches import BatchStore, StationBatch
from lake.feed.records import RawRecord, normalize_records
from lake.storage import Database, LakeError


def ingest(database: Database, batch_id: str, records: Iterable[RawRecord]) -> StationBatch:
    original = tuple(records)
    normalized = normalize_records(batch_id, original)
    with database.transaction(write=True) as conn:
        batches = BatchStore(conn)
        prior = batches.find(batch_id)
        if prior is not None:
            if prior.raw_records != original:
                raise LakeError('conflict', f'Batch {batch_id!r} already has different source records')
            return prior
        batch = StationBatch(batch_id, original, normalized, sum(row.missing for row in normalized))
        batches.insert(batch)
        return batch
