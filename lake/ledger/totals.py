from dataclasses import dataclass

from lake.ledger.detail import LedgerLine


@dataclass(frozen=True)
class LedgerTotals:
    litres: int
    missing_count: int
    missing_positions: tuple[int, ...]


def calculate_totals(lines: tuple[LedgerLine, ...]) -> LedgerTotals:
    litres = 0
    missing_positions = []
    for line in lines:
        if line.missing:
            missing_positions.append(line.position)
        else:
            litres += line.litres
    return LedgerTotals(litres, len(missing_positions), tuple(missing_positions))
