from __future__ import annotations

from collections.abc import Iterable

from lake.custody.basis import BasisObligations, read_exact_basis
from lake.custody.eligibility import check_public_eligibility
from lake.editions.manifest import ManifestStore
from lake.receiving.commitments import PartCommitment, missing_parts, validate_part_id
from lake.receiving.parts import PartReceipt, PartStore, Replacement, validate_replacements
from lake.receiving.requests import RequestStore, SupplementRequest
from lake.storage import Checkpoint, Database, LakeError, notify, require_name


def _verify_terms(
    request: SupplementRequest, parent_id: str, commitment: PartCommitment,
    part_id: str, replacements: tuple[Replacement, ...],
) -> None:
    if (request.parent_id, request.commitment) != (parent_id, commitment):
        raise LakeError('conflict', f'Supplement {request.supplement_id!r} has a different parent or commitment')
    if part_id == request.first_part_id and replacements != request.first_replacements:
        raise LakeError('conflict', f'The first material for {request.supplement_id!r} has different replacements')
    if request.status == 'rejected':
        raise LakeError('expired', f'Edition {parent_id!r} is closed to new supplements')


def materialize_first_part(parts: PartStore, request: SupplementRequest) -> None:
    """Persist the staged first material once custody has formally admitted it."""
    if parts.find(request.supplement_id, request.first_part_id) is not None:
        return
    covered = {part.part_id for part in parts.list_received(request.supplement_id)}
    covered.add(request.first_part_id)
    parts.insert(request.supplement_id, request.first_part_id, request.first_replacements,
                 missing_parts(request.commitment, covered))


def _receive(
    parts: PartStore, request: SupplementRequest, part_id: str, replacements: tuple[Replacement, ...],
) -> PartReceipt:
    prior = parts.find(request.supplement_id, part_id)
    if prior is not None:
        if prior.replacements != replacements:
            raise LakeError('conflict', f'Part {part_id!r} already has different replacements')
        return prior
    if request.status != 'admitted' or request.row_count is None:
        raise LakeError('basis_unavailable', f'No active receipt scope for supplement {request.supplement_id!r}')
    received = parts.list_received(request.supplement_id)
    occupied = (item.position for part in received for item in part.replacements)
    validate_replacements(replacements, request.row_count, occupied)
    covered = {part.part_id for part in received}
    covered.add(part_id)
    return parts.insert(request.supplement_id, part_id, replacements, missing_parts(request.commitment, covered))


def _authorize(
    custody: Database, request: SupplementRequest, parent_id: str, part_id: str,
) -> tuple[str, int, bool]:
    """Atomically decide admission against the exact parent and record its obligation.

    Eligibility and the first-material obligation share one custody write transaction,
    so an expiry either lands entirely before admission or entirely after it.
    """
    with custody.transaction(write=True) as conn:
        obligations = BasisObligations(conn)
        obligation = obligations.find(request.supplement_id)
        if obligation is not None:
            if obligation.edition_id != parent_id or obligation.binding != request.binding:
                raise LakeError('conflict',
                                f'Supplement {request.supplement_id!r} is bound to different custody terms')
            manifest = ManifestStore(conn).find(obligation.edition_id)
            if (manifest is None or manifest.digest != obligation.digest
                    or manifest.row_count != obligation.row_count):
                raise LakeError('basis_unavailable',
                                f'Edition {obligation.edition_id!r} no longer fits its admission')
            return obligation.digest, obligation.row_count, False
        # Staging alone never qualifies a supplement; the parent must still be open.
        check_public_eligibility(conn, parent_id)
        if part_id != request.first_part_id:
            raise LakeError('pending_first',
                            f'First material for {request.supplement_id!r} is awaiting admission')
        manifest = read_exact_basis(conn, parent_id).manifest
        newly_authorized = obligations.note_open_read(request.supplement_id, manifest, request.binding)
        return manifest.digest, manifest.row_count, newly_authorized


def submit_part(
    custody: Database, receiving: Database, supplement_id: str, parent_id: str,
    commitment: PartCommitment, part_id: str, replacements: Iterable[Replacement],
    *, checkpoint: Checkpoint | None = None,
) -> PartReceipt:
    require_name(supplement_id, 'supplement ID')
    require_name(parent_id, 'edition ID')
    validate_part_id(commitment, part_id)
    replacements = validate_replacements(replacements)

    with receiving.transaction() as conn:
        known = RequestStore(conn).find(supplement_id)
    manifest = None
    if known is None:
        # The immutable manifest is sufficient to validate coordinates before staging.
        with custody.transaction() as conn:
            manifest = ManifestStore(conn).find(parent_id)

    prepared = False
    with receiving.transaction(write=True) as conn:
        requests = RequestStore(conn)
        request = requests.find(supplement_id)
        if request is None:
            if manifest is None:
                raise LakeError('unknown_edition', f'Unknown edition {parent_id!r}')
            validate_replacements(replacements, manifest.row_count)
            request = requests.prepare(supplement_id, parent_id, commitment, part_id, replacements)
            prepared = True
        _verify_terms(request, parent_id, commitment, part_id, replacements)
        if request.status != 'staged':
            # Admitted or settled supplements keep working from their formal receipt scope.
            return _receive(PartStore(conn), request, part_id, replacements)
    if prepared:
        notify(checkpoint, 'first_staged', supplement_id)

    try:
        digest, row_count, newly_authorized = _authorize(custody, request, parent_id, part_id)
    except LakeError as error:
        if error.code == 'expired':
            with receiving.transaction(write=True) as conn:
                RequestStore(conn).reject(supplement_id)
        raise
    if newly_authorized:
        notify(checkpoint, 'first_authorized', supplement_id)

    with receiving.transaction(write=True) as conn:
        requests = RequestStore(conn)
        request = requests.find(supplement_id)
        _verify_terms(request, parent_id, commitment, part_id, replacements)
        parts = PartStore(conn)
        if request.status == 'staged':
            request = requests.record_admission(request, digest, row_count)
            materialize_first_part(parts, request)
        return _receive(parts, request, part_id, replacements)
