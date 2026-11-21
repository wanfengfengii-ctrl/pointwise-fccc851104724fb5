from lake.custody.basis import BasisObligations
from lake.custody.catalog import CustodyCatalog, CustodyState
from lake.editions.rows import EditionRowStore
from lake.ledger.lookup import read_ledger
from lake.storage import Database, LakeError, require_name


def _settled_supplements(receiving: Database, supplement_ids: tuple[str, ...]) -> set[str]:
    """Supplements whose fixed ledger and first receipt already exist.

    Publication commits only in the receiving database, so a lost reply after that
    commit can leave the custody-side release unapplied even though the ledger is fixed.
    """
    settled = set()
    with receiving.transaction() as conn:
        for supplement_id in supplement_ids:
            if read_ledger(conn, supplement_id) is not None:
                settled.add(supplement_id)
    return settled


def reclaim_edition(custody: Database, receiving: Database, edition_id: str) -> str:
    require_name(edition_id, 'edition ID')
    # Read the receiving side before taking the custody write lock: the two databases
    # commit independently and are never locked in a crossed order.
    with custody.transaction() as conn:
        state = CustodyCatalog(conn).state_for(edition_id)
        outstanding = BasisObligations(conn).outstanding(edition_id)
    if state == CustodyState.OPEN:
        raise LakeError('not_expired', f'Edition {edition_id!r} is still open')
    if state == CustodyState.RECLAIMED:
        return 'reclaimed'
    settled = _settled_supplements(receiving, tuple(item.supplement_id for item in outstanding))
    with custody.transaction(write=True) as conn:
        catalog = CustodyCatalog(conn)
        state = catalog.state_for(edition_id)
        if state == CustodyState.OPEN:
            raise LakeError('not_expired', f'Edition {edition_id!r} is still open')
        if state == CustodyState.RECLAIMED:
            return 'reclaimed'
        obligations = BasisObligations(conn)
        for supplement_id in settled:
            obligations.release(supplement_id)
        # Original rows stay while any admitted supplement still needs them.
        if obligations.outstanding(edition_id):
            return 'pending'
        EditionRowStore(conn).delete_exact(edition_id)
        catalog.mark_reclaimed(edition_id)
        return 'reclaimed'
