from collections.abc import Iterable
from dataclasses import dataclass

from lake.storage import LakeError, require_name


@dataclass(frozen=True)
class PartCommitment:
    part_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.part_ids, (tuple, list)) or not self.part_ids:
            raise LakeError('invalid_part', 'A commitment must contain an ordered list of part IDs')
        part_ids = tuple(self.part_ids)
        for part_id in part_ids:
            require_name(part_id, 'part ID', code='invalid_part')
        if len(part_ids) != len(set(part_ids)):
            raise LakeError('invalid_part', 'A commitment cannot repeat a part ID')
        object.__setattr__(self, 'part_ids', part_ids)


def validate_part_id(commitment: PartCommitment, part_id: str) -> None:
    require_name(part_id, 'part ID', code='invalid_part')
    if not isinstance(commitment, PartCommitment) or part_id not in commitment.part_ids:
        raise LakeError('invalid_part', f'Part {part_id!r} is outside the commitment')


def missing_parts(commitment: PartCommitment, received: Iterable[str]) -> tuple[str, ...]:
    received_ids = set(received)
    return tuple(part_id for part_id in commitment.part_ids if part_id not in received_ids)
