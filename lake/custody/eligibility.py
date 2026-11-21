import sqlite3

from lake.custody.catalog import CustodyCatalog, CustodyState
from lake.storage import LakeError


def check_public_eligibility(conn: sqlite3.Connection, edition_id: str) -> None:
    if CustodyCatalog(conn).state_for(edition_id) != CustodyState.OPEN:
        raise LakeError('expired', f'Edition {edition_id!r} is closed to new supplements')
