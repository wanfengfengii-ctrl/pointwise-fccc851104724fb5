from dataclasses import dataclass

from lake.storage import require_name


@dataclass(frozen=True)
class ReportSource:
    batch_id: str
    record_id: str
    source_name: str


def make_report_source(batch_id: str, record_id: str, source_name: str) -> ReportSource:
    require_name(batch_id, 'batch ID', code='invalid_record')
    require_name(record_id, 'record ID', code='invalid_record')
    require_name(source_name, 'source name', code='invalid_record')
    return ReportSource(batch_id, record_id, source_name)
