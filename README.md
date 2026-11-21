# 青汀河堤监测补档湖

报送员提交本班计量和缺测，归档班冻结日版。白班指定确切日版分段送更正，夜班按补档号核对整升合计及逐行出处。库管可以在两班之间令旧版到期，并在无剩余依赖时回收原行。

## 运行

使用 Python 3.11 标准库。在项目根目录运行以下命令。`check_project.py` 由项目控制台在物化时提供，运行 `tests` 包的完整回归。

```sh
python3 -B check_project.py
python3 -B -m lake demo
```

演示默认使用测试临时目录。加 `--directory ./demo-lake` 可保留两份 SQLite 库，在同一目录重跑会复用已存站批、发行、分段和成果。演示会经正式入口校验同号异参，已有业务数据按原内容保留。

## Python 接口

```python
from lake import Archive, Custodian, PartCommitment, RawRecord, Receiving, Replacement, initialize

initialize(directory)
archive = Archive(directory)
archive.ingest('batch-1', (
    RawRecord('up', '北堤', 7000, 'mL'),
    RawRecord('mid', '南堤', 11, 'L'),
    RawRecord('down', '尾闸', 5, 'L'),
))
parent = archive.freeze_edition('2026-10-12', 'batch-1', 'morning').edition_id
receiving = Receiving(directory)
parts = PartCommitment(('early', 'late'))
receiving.submit_part('A', parent, parts, 'early', (Replacement(0, 8),))
keeper = Custodian(directory)
keeper.expire_edition(parent)
archive.close()
receiving = Receiving(directory)
receiving.submit_part('A', parent, parts, 'late', (Replacement(1, 13),))
delivery = receiving.finish_supplement('A')
assert delivery.ledger.totals.litres == 26
assert keeper.reclaim_edition(parent) == 'reclaimed'
assert Receiving(directory).read_ledger('A') == delivery
```

- `initialize(directory)` 在指定目录建立缺失结构。`custody.sqlite3` 保存站批、发行和保管状态。`receiving.sqlite3` 保存分段实收、固定日账和成功首执。两库分别提交。
- `RawRecord` 依次接收记录身份、具名来源、值、单位和缺测标志。报送单位为 `L` 或 `mL`。实读须为整数，毫升实读须能精确换算成整升。缺测用 `None` 和 `missing=True`，实测零值保留。`ingest` 返回原序归一行、有效升数和缺测计数。按批号重投时比较完整原始输入。
- `freeze_edition(day, batch_id, issue_id)` 接收 ISO 业务日、已登记批号和发行请求号，返回含确切版号、行数、缺测数及原序摘要的清单。独立发行取得独立版号。`read_edition(edition_id)` 返回公开版清单和冻结行。`current_edition(day)` 返回该日最近发行的清单，无发行时返回 `None`，清单可在原行到期后继续查询。发行同参重投也可在原件回收后领取清单。
- `submit_part(supplement_id, parent_id, commitment, part_id, replacements)` 提交承诺内的一个段。承诺定义不重复的段标识及顺序，任一承诺内段可作为首段。替换按父版原顺序从零编号，段内及段间坐标互斥。段同参重投返回当次原实收，调整同段替换的列举顺序同样复用。实收回包记载该段入账时的缺段。
- `finish_supplement(supplement_id)` 在所承诺的所有段齐备时定稿。日账包含确切父版、原序明细、缺测位置、升数合计和逐行采用出处。报告行出处包含批号、记录身份和具名来源。更正行出处包含补档号、段号及原行位。`read_ledger(supplement_id)` 仅查本地定稿和首执，未发布返回 `None`。发布和成功首执同次提交。重开或失答后按原号可复领。
- `expire_edition(edition_id)` 关闭新开资格，重投仍确认到期。`custody_state(edition_id)` 查看当前实际保管状态。`reclaim_edition(edition_id)` 对有原件依赖的到期版返回 `pending`，实际删除原行后返回 `reclaimed`，重复回收沿用结果。已获准补档可在公开读入口关闭后使用本地保管原件。未到期版本拒绝回收。

业务拒绝以 `LakeError.code` 表示。常见值有 `invalid_record`、`invalid_unit`、`fractional_litre`、`duplicate_record`、`unknown_batch`、`unknown_edition`、`conflict`、`expired`、`invalid_part`、`invalid_coordinate`、`overlap`、`pending_first`、`not_admitted`、`incomplete`、`basis_unavailable` 和 `not_expired`。未齐定稿的异常附有按承诺顺序列出的 `missing`。数据库操作异常原样报告。业务有意暂停时，`Receiving` 可接收 `checkpoint(phase, supplement_id)` 回调。`first_staged` 和 `first_authorized` 位于库提交之后。`before_publication_commit` 位于实收事务内，可中断该事务，此时回调不应另开实收写事务。`after_publication_commit` 位于定稿提交之后。

## 样例核账

`samples/stations.json` 的确切父版为 `[7,11,5]`。`samples/supplement.json` 的两段分别将前两行更正为 8 L 和 13 L。父版在两段交班期间到期，同日后来发行的版次尾行是 50 L。演示停止报送和公开归档读取，重开实收后定稿为 `[8,13,5]`、26 L，第三行仍来自晨班父版的尾闸原记录。库管回收原件后，同一日账与首执仍可领取。
