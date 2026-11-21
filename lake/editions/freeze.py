from datetime import date

from lake.editions.history import EditionHistory
from lake.editions.manifest import EditionManifest, ManifestStore, summarize_edition
from lake.editions.rows import EditionRowStore, freeze_rows
from lake.feed.batches import BatchStore
from lake.storage import Database, LakeError, require_name


def validate_day(day: str) -> None:
    require_name(day, 'business day', code='invalid_day')
    try:
        parsed = date.fromisoformat(day)
    except ValueError as error:
        raise LakeError('invalid_day', 'Business day must use YYYY-MM-DD') from error
    if day != parsed.isoformat():
        raise LakeError('invalid_day', 'Business day must use YYYY-MM-DD')


def freeze_edition(database: Database, day: str, batch_id: str, issue_id: str) -> EditionManifest:
    validate_day(day)
    require_name(batch_id, 'batch ID')
    require_name(issue_id, 'issue ID')
    with database.transaction(write=True) as conn:
        history = EditionHistory(conn)
        manifests = ManifestStore(conn)
        issue = history.find_issue(issue_id)
        if issue is not None:
            if (issue.day, issue.batch_id) != (day, batch_id):
                raise LakeError('conflict', f'Issue {issue_id!r} already refers to a different day or batch')
            manifest = manifests.find(issue.edition_id)
            if manifest is None:
                raise LakeError('basis_unavailable', f'Issue {issue_id!r} has no edition manifest')
            return manifest
        batch = BatchStore(conn).find(batch_id)
        if batch is None:
            raise LakeError('unknown_batch', f'Unknown batch {batch_id!r}')
        edition_id = history.reserve_edition(day, batch_id, issue_id)
        rows = freeze_rows(batch.rows)
        manifest = summarize_edition(edition_id, day, rows)
        manifests.insert(manifest)
        EditionRowStore(conn).insert(edition_id, rows)
        return manifest
