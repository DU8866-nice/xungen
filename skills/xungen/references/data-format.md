# family.json 格式

一个家族一个 JSON 文件，UTF-8 编码。完整例子见 [`assets/family.example.json`](../assets/family.example.json)。只有 `people` 是必需的，其他字段知道多少写多少。

```json
{
  "title": "台山陈氏世系",
  "subtitle": "可选，显示在世系图标题下",
  "zibei": {"start_generation": 15, "chars": "德振家声远", "source": "s1"},
  "notes": "全族的说明，例如迁徙传说",
  "people": [ ... ],
  "sources": [ ... ]
}
```

## people

| 字段 | 说明 |
|---|---|
| `id` | 唯一编号，如 `p1` |
| `name` | 姓名；只知道姓的女性写 `黄氏` |
| `surname` | 姓。复姓、`某氏`、改过姓的人建议写上 |
| `sex` | `M` 或 `F` |
| `generation` | 第几世，按本支族谱的算法 |
| `pu_name`、`zi`、`hao` | 谱名、字、号 |
| `alt_names` | 其他名字：小名、外文名、同音异写 |
| `birth`、`death` | `{"text": 原文, "year": 公历年, "approx": true/false, "place": 地点}` |
| `father`、`mother` | 父母的 id |
| `spouses` | 配偶 id 列表。有共同子女的夫妻会自动识别 |
| `sources` | 出处 id 列表 |
| `status` | 可选，手动指定证据状态，见 [evidence.md](evidence.md) |
| `living` | 可选，`true` 或 `false`。不写时由脚本推断 |
| `legend` | `true` 表示传说或存疑，图上名字后加 `*` |
| `origin` | 祖籍（最早一代没有出生地时写这里） |
| `notes` | 备注 |

## sources

| 字段 | 说明 |
|---|---|
| `id` | 编号，如 `s1` |
| `title` | 名称，如 “《新宁陈氏族谱》民国二十五年续修本” |
| `short` | 短名，世系表里用 |
| `kind` | `original`、`derivative`、`oral`、`index` |
| `where` | 收藏地：家藏、某祠堂、某档案馆及档案号 |
| `detail` | 卷、页、档案号、碑文摘录 |
| `group` | 同一份记录的不同副本用同一个 group，算一个出处 |

## 输出

```bash
python3 scripts/family.py check family.json              # 检查，打印问题和待查清单
python3 scripts/family.py all family.json -o out/        # tree.svg、family.ged、tree.md、check.md
python3 scripts/family.py all family.json -o share/ --public   # 隐去在世者，用于分享
```

`family.ged` 是 GEDCOM 5.5.1 格式（UTF-8），可以导入 Gramps、MyHeritage、Ancestry、FamilySearch 等家谱软件。原始日期写在每个事件的 NOTE 里。
