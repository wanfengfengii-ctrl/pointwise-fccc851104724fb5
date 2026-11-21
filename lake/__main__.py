import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from . import Archive, Custodian, LakeError, PartCommitment, PartSource, RawRecord, Receiving, Replacement, ReportSource
from . import initialize


SAMPLES = Path(__file__).resolve().parent.parent / 'samples'


def _sample(name):
    return json.loads((SAMPLES / name).read_text(encoding='utf-8'))


def _issue(archive, day, batch):
    archive.ingest(batch['batch_id'], tuple(RawRecord(**item) for item in batch['records']))
    return archive.freeze_edition(day, batch['batch_id'], batch['issue_id'])


def _require(condition, message):
    if not condition:
        raise AssertionError(message)


def demo(directory):
    stations = _sample('stations.json')
    supplement = _sample('supplement.json')
    day = stations['day']
    identifier = supplement['supplement_id']
    (first, rest) = supplement['parts']
    commitment = PartCommitment((first['id'], rest['id']))
    head = tuple(Replacement(**item) for item in first['replacements'])
    tail = tuple(Replacement(**item) for item in rest['replacements'])

    initialize(directory)
    archive = Archive(directory)
    keeper = Custodian(directory)
    receiving = Receiving(directory)
    parent = _issue(archive, day, stations['morning'])
    already_published = receiving.read_ledger(identifier) is not None
    first_receipt = receiving.submit_part(identifier, parent.edition_id, commitment, first['id'], head)
    _require(first_receipt.missing == (rest['id'],), 'first part recorded the wrong outstanding commitment')
    keeper.expire_edition(parent.edition_id)
    newer = _issue(archive, day, stations['later'])
    _require(newer.edition_id != parent.edition_id, 'new issue reused the parent edition ID')
    later_values = [row.litres for row in archive.read_edition(newer.edition_id).rows]
    _require(later_values == [7, 11, 50], 'later station edition does not match the sample')
    archive.close()
    early_reclaim = keeper.reclaim_edition(parent.edition_id)

    receiving = Receiving(directory)
    tail_receipt = receiving.submit_part(identifier, parent.edition_id, commitment, rest['id'], tail)
    _require(tail_receipt.missing == (), 'all parts have arrived')
    delivery = receiving.finish_supplement(identifier)
    values = [row.litres for row in delivery.ledger.lines]
    litres = delivery.ledger.totals.litres
    _require(values == [8, 13, 5] and litres == 26,
             f'WRONG_DELTA_BASE expected 26 L [8, 13, 5], actual {litres} L {values}')
    _require(delivery.ledger.parent_id == parent.edition_id, 'delivery records the wrong parent edition')
    origins = [row.source for row in delivery.ledger.lines]
    _require(origins == [PartSource(identifier, first['id'], 0), PartSource(identifier, rest['id'], 1),
                         ReportSource('morning', 'tail', '尾闸')], 'delivery changed row provenance')
    _require(early_reclaim == ('reclaimed' if already_published else 'pending'), 'wrong pre-settlement reclaim result')
    try:
        receiving.submit_part(supplement['late_request_id'], parent.edition_id, commitment, first['id'], head)
    except LakeError as error:
        if error.code != 'expired':
            raise
        late_status = error.code
    else:
        raise AssertionError('a new supplement was admitted after expiry')
    _require(receiving.read_ledger(supplement['late_request_id']) is None, 'rejected supplement has a ledger')
    reclaimed = keeper.reclaim_edition(parent.edition_id)
    _require(reclaimed == 'reclaimed', 'settled basis could not be reclaimed')
    initialize(directory)
    reopened = Receiving(directory).read_ledger(identifier)
    _require(reopened == delivery, 'reopened ledger or receipt changed')
    observation = {
        'case_id': 'v06.original_basis',
        'input': {'parent_litres': [7, 11, 5], 'new_edition_litres': later_values, 'replacements': [8, 13]},
        'expected': {'litres_by_row': [8, 13, 5], 'total_litres': 26, 'tail_source': '尾闸'},
        'actual': {'litres_by_row': values, 'total_litres': litres, 'tail_source': origins[-1].source_name},
        'downstream_expected': {'late_request': 'expired', 'custody': 'reclaimed', 'reopened_total': 26, 'same_first_receipt': True},
        'downstream_actual': {'late_request': late_status, 'custody': reclaimed,
                              'reopened_total': reopened.ledger.totals.litres,
                              'same_first_receipt': reopened.receipt == delivery.receipt},
        'code_paths': ['lake/custody/basis.py', 'lake/custody/expiry.py', 'lake/receiving/admission.py',
                       'lake/receiving/assembly.py', 'lake/ledger/totals.py', 'lake/custody/reclaim.py', 'lake/ledger/lookup.py'],
        'oracle': 'Apply the two literal replacements at positions 0 and 1 of the morning edition. Keep the original tail and add 8 + 13 + 5.',
    }
    print('POINTWISE_SCENARIO ' + json.dumps(observation, ensure_ascii=False, sort_keys=True))
    print(json.dumps(asdict(reopened), ensure_ascii=False, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description='青汀河堤监测补档湖')
    commands = parser.add_subparsers(dest='command', required=True)
    demo_command = commands.add_parser('demo', help='执行站批、隔班补档、到期回收和独立领取')
    demo_command.add_argument('--directory', type=Path)
    args = parser.parse_args()
    try:
        if args.directory is None:
            with TemporaryDirectory(prefix='qingting-lake-') as directory:
                demo(directory)
        else:
            demo(args.directory)
    except (AssertionError, LakeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
