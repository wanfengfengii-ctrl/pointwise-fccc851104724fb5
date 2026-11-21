from lake.custody.catalog import CustodyCatalog, CustodyState
from lake.storage import Database, require_name


def expire_edition(database: Database, edition_id: str) -> CustodyState:
    require_name(edition_id, 'edition ID')
    with database.transaction(write=True) as conn:
        catalog = CustodyCatalog(conn)
        if catalog.state_for(edition_id) == CustodyState.OPEN:
            catalog.mark_expired(edition_id)
        return CustodyState.EXPIRED
