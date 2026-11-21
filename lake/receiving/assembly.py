from __future__ import annotations

from lake.custody.basis import BasisObligations, read_exact_basis
from lake.editions.manifest import ManifestStore
from lake.editions.rows import FrozenRow
from lake.ledger.detail import LedgerLine
from lake.ledger.lookup import read_ledger
from lake.ledger.publication import LedgerDelivery, publish_ledger
from lake.receiving.admission import materialize_first_part
from lake.receiving.commitments import missing_parts
from lake.receiving.parts import PartReceipt, PartSource, PartStore, validate_replacements
from lake.receiving.requests import RequestStore
from lake.storage import Checkpoint, Database, LakeError, notify, require_name


def apply_replacements(rows: tuple[FrozenRow, ...], parts: tuple[PartReceipt, ...]) -> tuple[LedgerLine, ...]:
    validate_replacements((item for part in parts for item in part.replacements), len(rows))
    changed = {
        item.position: LedgerLine(item.position, item.litres, PartSource(part.supplement_id, part.part_id, item.position))
        for part in parts for item in part.replacements
    }
    return tuple(
        changed[row.position] if row.position in changed else LedgerLine(row.position, row.litres, row.source)
        for row in rows
    )


def _snapshot(receiving: Database, supplement_id: str):
    with receiving.transaction() as conn:
        result = read_ledger(conn, supplement_id)
        if result is not None:
            return result, None, ()
        request = RequestStore(conn).find(supplement_id)
        return None, request, PartStore(conn).list_received(supplement_id)


def _release(custody: Database, supplement_id: str) -> None:
    with custody.transaction(write=True) as conn:
        BasisObligations(conn).release(supplement_id)


def _recover_admission(custody: Database, receiving: Database, supplement_id: str) -> None:
    """Promote a staged first part that custody already authorized before a lost reply.

    Formal admission lives in custody, so a staged receiving row may be waiting only on
    the local write that followed it. The exact parent and digest come from the recorded
    obligation rather than from any newer edition.
    """
    with receiving.transaction() as conn:
        request = RequestStore(conn).find(supplement_id)
    if request is None or request.status != 'staged':
        return
    with custody.transaction() as conn:
        obligation = BasisObligations(conn).find(supplement_id)
        if obligation is None:
            return
        if obligation.edition_id != request.parent_id or obligation.binding != request.binding:
            raise LakeError('conflict', f'Supplement {supplement_id!r} is bound to different custody terms')
        manifest = ManifestStore(conn).find(obligation.edition_id)
        if manifest is None or manifest.digest != obligation.digest or manifest.row_count != obligation.row_count:
            raise LakeError('basis_unavailable', f'Edition {obligation.edition_id!r} no longer fits its admission')
        digest, row_count = obligation.digest, obligation.row_count
    with receiving.transaction(write=True) as conn:
        requests = RequestStore(conn)
        current = requests.find(supplement_id)
        if current is not None and current.status == 'staged':
            current = requests.record_admission(current, digest, row_count)
            materialize_first_part(PartStore(conn), current)


def finish_supplement(
    custody: Database, receiving: Database, supplement_id: str, *, checkpoint: Checkpoint | None = None,
) -> LedgerDelivery:
    require_name(supplement_id, 'supplement ID')
    delivery, request, parts = _snapshot(receiving, supplement_id)
    if delivery is not None:
        _release(custody, supplement_id)
        return delivery
    _recover_admission(custody, receiving, supplement_id)
    delivery, request, parts = _snapshot(receiving, supplement_id)
    if delivery is not None:
        _release(custody, supplement_id)
        return delivery
    if request is None or request.status in ('staged', 'rejected'):
        raise LakeError('not_admitted', f'Supplement {supplement_id!r} has no formal admission')
    covered = {part.part_id for part in parts}
    missing = missing_parts(request.commitment, covered)
    if missing:
        raise LakeError('incomplete', f'Supplement {supplement_id!r} is waiting for parts {missing!r}', missing=missing)
    if covered != set(request.commitment.part_ids) or request.digest is None or request.row_count is None:
        raise LakeError('basis_unavailable', f'Supplement {supplement_id!r} lacks verified material')
    try:
        # The ledger is always assembled from the supplement's exact parent edition.
        # A later edition for the same day is never substituted for the committed basis.
        with custody.transaction() as conn:
            evidence = read_exact_basis(conn, request.parent_id)
            if (evidence.manifest.row_count != request.row_count
                    or evidence.manifest.digest != request.digest):
                raise LakeError('basis_unavailable', f'Basis does not fit supplement {supplement_id!r}')
    except LakeError:
        # A concurrent finisher may have published and allowed reclaim since our first snapshot.
        with receiving.transaction() as conn:
            prior = read_ledger(conn, supplement_id)
        if prior is not None:
            _release(custody, supplement_id)
            return prior
        raise
    lines = apply_replacements(evidence.rows, parts)
    with receiving.transaction(write=True) as conn:
        prior = read_ledger(conn, supplement_id)
        if prior is not None:
            return prior
        delivery = publish_ledger(conn, supplement_id, request.parent_id, lines)
        RequestStore(conn).mark_settled(supplement_id)
        notify(checkpoint, 'before_publication_commit', supplement_id)
    notify(checkpoint, 'after_publication_commit', supplement_id)
    _release(custody, supplement_id)
    return delivery
