from lake.custody.catalog import CustodyCatalog, CustodyState
from lake.editions.rows import EditionRowStore
from lake.storage import Database, LakeError, require_name


def reclaim_edition(custody: Database, receiving: Database, edition_id: str) -> str:
    require_name(edition_id, 'edition ID')
    with custody.transaction(write=True) as conn:
        catalog = CustodyCatalog(conn)
        state = catalog.state_for(edition_id)
        if state == CustodyState.OPEN:
            raise LakeError('not_expired', f'Edition {edition_id!r} is still open')
        if state == CustodyState.RECLAIMED:
            return 'reclaimed'
        EditionRowStore(conn).delete_exact(edition_id)
        catalog.mark_reclaimed(edition_id)
        return 'reclaimed'
