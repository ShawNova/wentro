# 温途 (Wentro)

[English](README.md)

Wentro — retrace the journey you went. 温途——重温你走过的路。

## 这是什么

温途是一个 [Claude Code](https://claude.com/claude-code) 技能（skill），用来把你**已经走完**
的一段旅程变成一张地图。你只需要用对话告诉 Claude 你去了哪里——想用什么语言描述都行——它会：

- 通过 [Nominatim](https://nominatim.org/) **地理编码**，把地名解析成真实坐标；
- 通过 FOSSGIS 提供的公共 [OSRM](http://project-osrm.org/) 服务**获取真实路线**（步行、骑行、
  驾车都支持；公共交通没有免费的全球路由 API，所以那部分路段只画成示意线）；
- 拼接一张真实的 [OpenStreetMap](https://www.openstreetmap.org/copyright) 底图铺在路线下面；
- 最终发布一张可交互的 Claude Artifact 地图，外加一张静态 PNG 图片，可以直接发到聊天或者
  发在博客里。

温途刻意**不是**一个行程规划工具。它不会帮你搜"有什么好玩的"，不会给行程建议，也不会做路线
优化。输入永远是一段你已经走过（或者开车、骑车走过）的路——温途做的是复盘和分享，不是规划。

## 为什么这些工作发生在对话侧

发布出去的 Claude Artifact 运行在严格的内容安全策略（CSP）下：不允许发出任何网络请求。这意味
着地图本身没法在 artifact 内部去请求瓦片或调用路由 API。所以温途反过来做：所有实时数据工作
（地理编码、路由、瓦片下载）都在**你和 Claude 对话的过程中**完成，由本仓库里的脚本执行，然后把
结果全部打包进一个自包含的 HTML 页面里。发布出去的 artifact 从此不需要再联网，也确实不会联网。

## 安装

skill 文件夹是自包含的——安装就是把它拷到位：

```bash
git clone --depth 1 https://github.com/ShawNova/wentro.git /tmp/wentro
mkdir -p ~/.claude/skills && cp -r /tmp/wentro/skill ~/.claude/skills/wentro && rm -rf /tmp/wentro
```

无需其他配置：首次使用时 skill 会自动检测 Python ≥ 3.10，并把两个依赖
（`requests`、`Pillow`）装进 `~/.wentro/venv`。

如果要参与开发，改用 clone + 软链，让已安装的 skill 跟随你的工作树：

```bash
git clone https://github.com/ShawNova/wentro.git
cd wentro && pip install -r requirements-dev.txt
mkdir -p ~/.claude/skills && ln -sfn "$(pwd)/skill" ~/.claude/skills/wentro
```

## 使用方法

直接跟 Claude 聊你的行程就行。如果你给的信息不完整，Claude 不会替你瞎猜，而是给出这个模板：

> - 地区（城市或国家）：……
> - 按游览顺序列出的地点：……
> - 你是怎么在这些地点之间移动的（默认步行）：……

最小可用输入是一个地区加两个以上的地点，语言不限。

**创建**行程，交通方式可以随意混用：

> 我在罗马逛了一圈——先去斗兽场，然后古罗马广场，然后特雷维喷泉，接着打车去了万神殿，
> 最后走到纳沃纳广场。

Claude 会对每个地点做地理编码，对每一段路做路由（步行段用步行路由，打车那段用驾车路由），
拼好底图，然后回复你 artifact 链接和解析出来的地点名称列表，方便你核对。

**新增一个地点**到已有的行程里：

> 在特雷维喷泉之后加一个站，那家喷泉旁边的冰淇淋店。

Claude 会插入这个新点，只重新计算跟它相邻的两段路线，然后发布到**同一个** artifact 链接上，
而不是生成一个新链接。

**修正一段走错的路线**：

> 从古罗马广场到特雷维喷泉那段实际上是沿着河边走的，不是穿过威尼斯广场。

Claude 会根据你的描述推出一个 `via` 修正点，只重新计算这一段路线，然后重新发布——这个修正
会保存在行程文件里，下次重新生成地图时不会再走回错的那条路。

**删除一个地点**：

> 其实我们跳过了纳沃纳广场，没去。

Claude 会删掉这个点，把它两边的路段合并成一段，重新路由，然后重新发布。

## 卸载

```bash
rm -rf ~/.claude/skills/wentro ~/.wentro/venv
```

移除 skill 及其自动创建的 Python 环境。`~/.wentro/itineraries/` 里的行程数据
会保留，确实不要了再整个删除 `~/.wentro`。也可以直接对 Claude 说「卸载
wentro」，skill 自带的工作流会执行同样的清理。（开发者：第一个路径是软链，
仓库和它的 `.venv` 由你自己管理。）

## 数据

每一段行程就是一个 JSON 文件——它是唯一的数据来源（source of truth）。只要这个文件已经存在，
Claude 就绝不会凭聊天记忆重新生成地图，而是加载并编辑这个文件。这意味着一段行程可以跨会话
保存下来，之后任何一次新对话都能接着编辑它。

数据目录的解析规则：如果当前工作目录下存在 `./itineraries/`，就用它（适合你在本仓库的克隆
目录里操作）；否则使用 `~/.wentro/itineraries/`（首次使用时自动创建）。完整的字段说明见
[`docs/data-format.zh-CN.md`](docs/data-format.zh-CN.md)，一个可以参考的示例见
[`examples/rome-walk.json`](examples/rome-walk.json)。

## 使用礼仪与署名

温途调用的是志愿者维护的公共基础设施，因此遵守每个服务各自的使用规范：

- **Nominatim** —— 地理编码，限速每秒最多 1 次请求，携带描述性的 User-Agent。
- **FOSSGIS OSRM**（`routing.openstreetmap.de`）—— 步行/骑行/驾车路由，低频调用，携带描述性
  的 User-Agent。
- **OpenStreetMap 瓦片服务器** —— 底图瓦片，逐张下载、每次请求之间有短暂停顿，每次构建最多
  下载 80 张瓦片，并携带描述性的 User-Agent。

每一张生成的地图和 PNG 图片上都会带上必需的 **© OpenStreetMap contributors** 署名。

## 路线图

- 每个地点插入照片——数据模型里 `photos` 字段已经预留好了，只是这一版还不渲染。

## 许可证

MIT —— 见 [LICENSE](LICENSE)。
