from __future__ import annotations

import json
from dataclasses import dataclass

from lake.feed.provenance import ReportSource
from lake.receiving.parts import PartSource
from lake.storage import LakeError, decode_quantity, encode_quantity, json_text


@dataclass(frozen=True)
class LedgerLine:
    position: int
    litres: int | None
    source: ReportSource | PartSource

    @property
    def missing(self) -> bool:
        return self.litres is None


def encode_detail(lines: tuple[LedgerLine, ...]) -> str:
    payload = []
    for line in lines:
        source = line.source
        if isinstance(source, ReportSource):
            origin = ('report', source.batch_id, source.record_id, source.source_name)
        else:
            origin = ('part', source.supplement_id, source.part_id, source.position)
        payload.append((line.position, encode_quantity(line.litres), origin))
    return json_text(payload)


def decode_detail(payload: str) -> tuple[LedgerLine, ...]:
    lines = []
    for position, litres, (kind, first, second, third) in json.loads(payload):
        if kind == 'report':
            source = ReportSource(first, second, third)
        elif kind == 'part':
            source = PartSource(first, second, third)
        else:
            raise LakeError('invalid_ledger', f'Unknown ledger provenance kind {kind!r}')
        lines.append(LedgerLine(position, decode_quantity(litres), source))
    return tuple(lines)
