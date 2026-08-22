# 行程数据格式

[English](data-format.md)

每一段行程都是一个 JSON 文件，路径是 `<数据目录>/<slug>.json`，它是唯一的数据来源
（source of truth）：Claude 会加载并编辑这个文件，而不是凭聊天记忆重新生成地图；之后任何
一次新会话都能接着编辑它。仓库里有一份完整示例：
[`examples/rome-walk.json`](../examples/rome-walk.json)。

## 数据目录

脚本按下面的顺序解析行程文件存放在哪里：

1. 当前工作目录下的 `./itineraries/`，如果它存在——也就是你在本仓库的克隆目录里操作时的
   情况。
2. 否则使用 `~/.wentro/itineraries/`——全局默认位置，首次使用时自动创建。

## 带注释的示例

```json
{
  "title": "Classic Rome Walk",
  "region": "Rome, Italy",
  "points": [
    {
      "id": "p1",
      "name": "斗兽场",
      "query": "Colosseum, Rome",
      "resolved": "Colosseo, Roma",
      "lat": 41.8902,
      "lon": 12.4922,
      "photos": []
    }
  ],
  "legs": [
    {
      "from": "p1", "to": "p2", "mode": "foot",
      "via": [],
      "geometry": "<polyline5-encoded geometry (OSRM default)>",
      "distance_m": 850, "duration_s": 640
    },
    {
      "from": "p2", "to": "p3", "mode": "transit",
      "note": "Metro line B, ~8 min"
    }
  ],
  "artifact_url": null,
  "updated": "2026-08-22"
}
```

## 顶层字段

| 字段 | 类型 | 含义 |
|---|---|---|
| `title` | string | 行程的可读名称，显示在地图和侧边栏上。 |
| `region` | string | 声明的地区（城市或国家），例如 `"Rome, Italy"`。用于给地理编码加偏置（Nominatim 的 `viewbox`），也用于检查每个解析出的地点是否真的落在这个地区内。 |
| `points` | array | 按游览顺序排列的地点列表。字段说明见下面的"地点字段"。 |
| `legs` | array | 相邻地点之间的连接列表，顺序对应。字段说明见下面的"路段字段"。 |
| `artifact_url` | string \| null | 已发布的 Claude Artifact 链接；首次发布之前是 `null`。重新发布时会把这个值传回去，这样更新会落在同一个链接上，而不是生成一个新链接。 |
| `updated` | string | 最后一次写入的 ISO 日期（`YYYY-MM-DD`）。每次保存文件时自动更新。 |

## 地点字段

`points` 里每一项代表旅程中的一个停靠点：

| 字段 | 类型 | 含义 |
|---|---|---|
| `id` | string | 该地点的稳定标识（例如 `"p1"`），会被 `legs[].from` / `legs[].to` 引用。在同一份行程内唯一。 |
| `name` | string | 显示名称，保留用户自己的说法和语言——地理编码过程绝不会覆盖它。 |
| `query` | string | Claude 根据 `name` 构造出的规范地理编码查询词：纠正了拼写错误，翻译成当地语言或英语，并补上了城市/地区上下文。 |
| `resolved` | string | Nominatim 针对 `query` 返回的规范地址字符串。 |
| `lat`, `lon` | number | 解析出的坐标（WGS84 十进制度）。 |
| `photos` | array | **预留字段。** 本版本不渲染——参见 README 里的"路线图"部分。始终以（空）数组形式存在，这样未来版本可以直接填充它，不需要做数据迁移。 |

## 路段字段

`legs` 里每一项连接 `points[i]` 和 `points[i+1]`：

| 字段 | 类型 | 含义 |
|---|---|---|
| `from`, `to` | string | 这段路两端的地点 id。必须满足下面的"链式不变量"。 |
| `mode` | string | `foot`、`bike`、`car`、`transit` 之一。始终显式写出——数据格式里没有隐含的默认值。 |
| `via` | array | 非 `transit` 路段的修正点列表，每项是 `[lat, lon]`（默认空数组）。语义见下面的"`via` 语义"。`transit` 路段没有这个字段。 |
| `geometry` | string \| null | OSRM 返回的路线几何，polyline5 编码（OSRM 的默认编码方式）。`null` 表示无法计算出路线——地图会退化成一条标注为"近似"的直线虚线。`transit` 路段没有这个字段。 |
| `distance_m` | number \| null | OSRM 给出的路线距离（米）。`transit` 路段没有这个字段。 |
| `duration_s` | number \| null | OSRM 给出的路线用时（秒）。`transit` 路段没有这个字段。 |
| `note` | string | `transit` 路段的人工描述文字（例如 `"Metro line B, ~8 min"`），因为公共交通路段不做真实路由。只在 `transit` 路段上出现。 |

### `mode` 的取值

`foot`、`bike`、`car` 会通过 FOSSGIS 提供的 OSRM 实例（分别对应 `routed-foot`、
`routed-bike`、`routed-car`）路由，得到真实的路线几何。`transit` 路段永远不会被路由——
目前没有免费的全球公共交通路由 API——而是画成一条带 `note` 标签的示意虚线。

### `via` 语义

`via` 保存用户提供的路段修正坐标，用于修正一段路由结果和实际走的路不一致的情况（比如 OSRM
选了另一条街，或者漏掉了一次绕行）。只要 `via` 不为空，`route.py` 就会依次经过这些点，串联
`from` 和 `to`。这些修正会被持久化保存在文件里，专门是为了让后续重新生成地图时（比如在别处
新增了一个地点）不会把之前修好的路段又带回错误的路线。

## 链式不变量

`legs` 必须构成一条单一的链，按数组顺序依次串联 `points`：

- `legs[i].from == points[i].id`
- `legs[i].to == points[i + 1].id`
- 路段数量恰好等于 `len(points) - 1`。

正是这个约束让一份行程是一条连续的路线，而不是一堆互不相连的散点。脚本在每次读取和保存时
都会校验这个不变量（`common.validate_chain`），一旦文件违反了它，就拒绝渲染、也拒绝写入。
涉及改变地点顺序的编辑（插入、删除）必须在同一次操作里同步更新相邻的路段，保持链条完整；
具体流程见 `skill/SKILL.md` 里的"更新 / 删除"部分。
