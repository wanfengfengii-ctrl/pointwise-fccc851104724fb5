from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from lake.feed.provenance import ReportSource, make_report_source
from lake.feed.units import to_whole_litres, validate_unit
from lake.storage import LakeError, require_name


@dataclass(frozen=True)
class RawRecord:
    record_id: str
    source_name: str
    value: int | None
    unit: str
    missing: bool = False


@dataclass(frozen=True)
class NormalizedRecord:
    litres: int | None
    source: ReportSource

    @property
    def missing(self) -> bool:
        return self.litres is None


def normalize_records(batch_id: str, records: Iterable[RawRecord]) -> tuple[NormalizedRecord, ...]:
    require_name(batch_id, 'batch ID')
    seen = set()
    normalized = []
    for record in records:
        if not isinstance(record, RawRecord) or type(record.missing) is not bool:
            raise LakeError('invalid_record', 'Expected a raw record with a Boolean missing flag')
        source = make_report_source(batch_id, record.record_id, record.source_name)
        if source.record_id in seen:
            raise LakeError('duplicate_record', f'Record {source.record_id!r} appears twice in the batch')
        seen.add(source.record_id)
        if record.missing:
            validate_unit(record.unit)
            if record.value is not None:
                raise LakeError('invalid_record', 'A missing record must carry a null value')
            litres = None
        else:
            litres = to_whole_litres(record.value, record.unit)
        normalized.append(NormalizedRecord(litres, source))
    return tuple(normalized)
