from lake.storage import LakeError


SUPPORTED_UNITS = frozenset(('L', 'mL'))


def validate_unit(unit: str) -> None:
    if not isinstance(unit, str) or unit not in SUPPORTED_UNITS:
        raise LakeError('invalid_unit', f'Unsupported unit {unit!r}')


def to_whole_litres(value: int, unit: str) -> int:
    validate_unit(unit)
    if type(value) is not int:
        raise LakeError('invalid_record', 'A measured quantity must be an integer')
    if unit == 'L':
        return value
    litres, remainder = divmod(value, 1000)
    if remainder:
        raise LakeError('fractional_litre', 'Millilitres must convert to a whole number of litres')
    return litres
