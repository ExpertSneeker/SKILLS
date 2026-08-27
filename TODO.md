# Todo list

## temu-img
> temu-img Skill的功能实现

- [x] 除了定制品之外的产品需要传入产品尺寸，理解产品在现实中的大小，但是不要显式的出现在图中(尺寸图除外)，加在 ## 额外添加的提示词 里
- [x] 挑选的 edit_target 图片如果展示的是完整产品，必须优先选择能清晰呈现产品整体三维结构的斜俯视三分之四视角（约 30°–45°），确保产品整体轮廓、顶面、侧面、厚度及前后纵深关系清晰可见；不得使用主体被裁切、关键结构被遮挡或因视角过平导致结构难以判断的图片。
- [x] 取消单图生成之后的验收，取消最终挑选FINAL的流程，生图后直接保存，冗余的重新生成repair也去掉
- [x] 单图Subagent生图完毕返回结果后，主Agent无需查看图片
- [x] 主图文字(如果有)必须直接加在背景图(场景图)上面，文字与背景之间不要加底色。
- [x] 强化产品一致性，优化提示词，参考：https://learn.chatgpt.com/docs/image-generation
- [x] 多颜色&多PC SKU只生成同一种颜色的不同PC SKU, 且每种PC的SKU单独一张(解决冲突，修改原有的只生成一张SKU)
- [x] 坐垫类产品如果出现在沙发上，则应该用产品代替沙发原有的坐垫。
- [x] 读取产品拍摄图的时候只读取JPG/PNG, 不要读取相机raw源格式, 比如.ARW,.CR2等等.
- [x] 解决完全生成整套图之前Session意外中止问题
- [x] 校验: 尺寸是否与载体一致，不留空
- [x] 区分单图直出后的校验与FINAL终验，并给出校验未通过的解决方案
- [x] 针对多PC产品要求同场景内使用多个产品
- [x] 最小改动优化Skill图片生成风格提示词中的文案字体/配色来源/版式等

---

- [ ] 风格一致性优化
    - [ ] 检测当前目录中 ./DESIGN.md 是否存在，如果有，本套图的风格应当遵守DESIGN.md中
    - [ ] 执行完一套图后，如果不存在./DESIGN.md ，则根据本套图的视觉风格/色调/字体/字体配色进行提取，创建DESIGN.md

---

- [x] 功能性优化
    - [x] 反推提示词时应该提取本张图片所要表达的卖点，以及体现卖点的元素
    - [x] 要可以做到即使去掉文案也能通过图片表达出本张图表达的意思（通过提示词来实现），在符合当前产品的情况下尽可能保留体现卖点的元素，不验收

---

- [x] 丰富文案与板式
    - [x] 副标题改为强制加入(如果有主标题)。
    - [x] 卖点的小标题必须配有正文，ICON下的卖点也必须带有正文(不要过长)。
    - [x] 如果需求表没提供文案且参考图中也没有的正文/副标题，那么就写一些宽泛的介绍说明，不要写具体可追责的参数。

---

- [x] 基于参考图优化的一致性提升方案
    - [x] 生成图片时不再传入需求表中带有产品的参考图 reference (以下对于参考图的表述皆为此类型的参考图)
    - [x] 输入图片中的产品实拍、颜色/面料、结构细节、插入素材等继续显式传入
    - [x] 规划提示词的时候，反推出参考图的版式布局/场景等内容，融入到现有的提示词模板中。不再提及未实际传入的“参考图”或图片编号。
    - [x] 取消掉skill中任何关于“只参考参考图的xxx”，“不参考参考图的xxx”，“参考参考图的xxx”等相关的表述
    - [x] 禁止从参考图提取竞品产品外观、Logo、品牌及未经需求表确认的文案。
    - [x] 内部规划记录保留反推提示词的参考图路径、角色和规格来源，确保可追踪


---

- [x] 每个 direct 使用独立生成 Subagent，隔离图片上下文
    - [x] 主 Agent 预先锁定三版提示词、共同产品基准和准确输入路径
    - [x] direct01、direct02、direct03 分别由全新 Subagent 串行生成，每个 Subagent 只调用一次生图工具
    - [x] 每次调用显式传入当前任务图片，禁止依赖其他 direct 或上一版会话图片
    - [x] 每张 direct 由全新验收 Subagent 重新查看产品图、面料图和输出图后单独判定 PASS/FAIL
    - [x] FAIL 版本由新的替补 Subagent 重做，不复用失败生成 Session
    - [x] 面料参考只提供颜色、印花和微观织纹，不得复制参考图的折叠、旋拧、褶皱和阴影形状
    - [x] 有载体时坐垫必须完整覆盖可用区域；非必要的堆叠主图优先不使用长凳等载体

---

- [x] 增加针对定制产品的规范
    - [x] 确认定制产品是否支持异型定制，如果不支持则只允许定制长宽，不允许梯形/三角形/圆角等
    - [x] 编写references/custom-product.md，编写关于定制模板/定制尺寸/系带/防滑底/滚边相关要求与参考
    - [x] 在SKILL.md中要求判断产品为定制产品则读取custom-product.md
    - [x] 不生成“定制模板”和“色号图”
    - [x] 针对摞起来展示的主图增加说明优化
    - [x] 主图摞起来的坐垫必须使用不同的颜色或面料
    - [x] 针对面料细节图做出优化
    - [x] 可定制产品的一致性问题(系带/滚边)，增加校验

---

- [x] 最小改动实现:
    - [x] 除了明确定义为"定制模板"的图片外, 所有出现的色块都不要出现颜色编号
    - [x] 主图上面如果要求添加色块，色块必须直接加在背景图(场景图)上面，色块与背景之间不要加底色。并且主图上的配色图不要加颜色编号或颜色名字

- [x] 完整读取 豆包Seedream-5.0 Pro 的生图原理/流程和规范：https://console.volcengine.com/ark/region:cn-beijing/docs/82379/2582774
    - [x] 最小改动实现接入 Seedream-5.0-Pro API 生图功能，编写references/seedream.md
    - [x] 在SKILL.md中的生图工具选择器中加入seedream.md的路径/别名与相关简单介绍

---

- [x] 开工前为当前任务准备独立的2560px拍摄图目录
    - [x] 读取需求表并确认任务根目录后，在固定路径`<任务根目录>\2560px拍摄图\`创建目录，不覆盖或修改拍摄原图
    - [x] 默认解析任务根目录下固定名称`产品拍摄原图.lnk`取得原始拍摄图目录，并允许显式传入源目录；不得递归扫描整个任务根目录
    - [x] 预处理脚本是唯一允许扫描或读取原始拍摄图目录的组件；仅打开JPG/JPEG/PNG图片，其他格式一律跳过，不复制、不转码、不执行view_image，也不提供给任何Agent或生图工具
    - [x] 目标图片保留源文件的相对子目录和原文件名，不因同名文件覆盖或重命名
    - [x] 原图长边不大于2560px时原样复制，不重新编码、不放大
    - [x] 原图长边大于2560px时保持正确EXIF方向和原始宽高比，等比缩放至长边2560px
    - [x] 记录原图与目标文件的路径、尺寸和哈希映射；源文件未变化且目标完整时复用，仅处理新增、变化、缺失或损坏的图片
    - [x] 筛选后没有可用拍摄图时按缺少产品实拍图阻塞

---

- [x] 后续Agent与生图工具仅使用2560px拍摄图目录
    - [x] 首次view_image、提示词规划、Agent分发或生图前，必须完成2560px拍摄图目录及映射记录
    - [x] 主Agent、Subagent、view_image和当前生图工具只允许读取映射中登记的目标文件，不直接读取或上传原始拍摄图
    - [x] 多Session复用同一任务时先校验映射，仅补充处理新增、变化、缺失或损坏的目标文件

---

## temu-img：平台规范路由与分层重构（Amazon / TEMU）

> 规划日期：2026-08-27  
> 状态：仅完成架构规划，暂不修改现有生成行为。  
> 目标：先确定本套图唯一所属平台，再读取“通用规范 + 命中平台规范”；Amazon 任务不得读取 TEMU 规范，TEMU 任务不得读取 Amazon 规范。

### 1. 重构边界与核心决策

- [ ] 第一阶段继续保留目录名、Skill 名和调用方式 `$temu-img`，避免破坏既有脚本、快捷调用与外部引用；仅将展示名称改为中性的“电商平台图片（Amazon / TEMU）”。
- [ ] 一次任务根目录只允许对应一个 `platform_id`；首期仅支持 `amazon`、`temu`。
- [ ] 将 `platform_id` 与 `marketplace` 分开记录。首期平台规范可仍以当前业务站点为范围，但不得把“Amazon/TEMU”与“US/JP/EU”等站点概念混为一体。
- [ ] 通用规范只保存跨平台不变量；平台文件只保存平台差异和站点差异，不在两个平台文件中复制通用规则。
- [ ] 平台文件不得覆盖产品真实性、manifest 门禁、唯一 `edit target`、色块映射、三版串行、生图来源追踪、技术重试上限等通用硬约束。
- [ ] 同一套图不得同时合并 Amazon 与 TEMU 规则；同一产品需要两个平台版本时，拆成两个独立任务上下文分别执行。
- [ ] 本次重构不改变三版直出逻辑、不改变生图工具 API、不新增平台、不重新定义具体平台规范内容；具体数值和政策在平台文件落地时另行核验。

### 2. 目标目录结构

```text
temu-img/
├── SKILL.md
├── agents/
│   └── openai.yaml
├── references/
│   ├── common/
│   │   ├── design-and-prompt.md
│   │   ├── generation-workflow.md
│   │   ├── delivery.md
│   │   └── custom-product.md
│   ├── platforms/
│   │   ├── index.md
│   │   ├── amazon.md
│   │   └── temu.md
│   └── tools/
│       ├── imagegen.md
│       └── seedream.md
└── scripts/
    ├── seedream5_pro.py
    └── test_seedream5_pro.py
```

- [ ] `SKILL.md` 只负责入口门禁、平台路由、模块加载顺序和总体编排，不再承载具体平台尺寸、语言、比例或主图规则。
- [ ] `references/platforms/index.md` 作为平台注册表与路由合同，只包含支持的平台 ID、别名、规范路径、平台判定规则及错误处理；不得把两个平台的完整规范都写入该文件。
- [ ] `references/platforms/amazon.md` 是 Amazon 唯一平台规范源。
- [ ] `references/platforms/temu.md` 是 TEMU 唯一平台规范源。
- [ ] `references/common/` 保存跨平台规则；`references/tools/` 保存与平台无关的工具适配器。
- [ ] 当单个平台文件膨胀到难以维护时，再升级为 `platforms/<platform>/index.md + design.md + delivery.md`；首期不提前拆成过多小文件。

### 3. 平台判定与冻结合同

- [ ] 在查看产品、规划提示词或读取任何完整平台规范前，先解析平台并得到唯一 `platform_id`。
- [ ] 平台来源只允许使用显式信息：
    1. 用户明确指定的平台；
    2. 需求表中明确的 `平台 / Platform / 渠道 / Site` 字段；
    3. 已存在且通过一致性校验的 `./output/_platform_context.json`，仅用于中断恢复。
- [ ] 不得仅根据文件夹名、文件名、语言、`A+`、图片比例、输出目录或历史会话猜测平台。
- [ ] 同时存在多个显式来源时先做一致性校验；值冲突时标记 `PLATFORM_CONFLICT` 并在生图前阻塞，不擅自选择优先级。
- [ ] 缺少平台时标记 `PLATFORM_REQUIRED`；平台不在注册表中时标记 `UNSUPPORTED_PLATFORM`；两种情况均不得默认回退到 Amazon 或 TEMU。
- [ ] 将别名统一映射到规范 ID，例如 `Amazon / 亚马逊 / Amazon US / 美亚 -> amazon`，`TEMU / Temu -> temu`；别名只维护在 `platforms/index.md`。
- [ ] 首次判定后冻结并写入 `./output/_platform_context.json`，至少记录：
    - `platform_id`
    - `marketplace`
    - `source`
    - `evidence`
    - `spec_path`
    - `spec_version`
    - `spec_sha256`
    - `resolved_at`
- [ ] Session 恢复时先读取该上下文，再与当前用户要求和需求表复核；平台或规范哈希发生变化时阻塞并要求重新规划，不在旧提示词上混用新规范。

### 4. 模块加载顺序

```text
入口门禁
  -> 读取 platforms/index.md
  -> 解析并冻结 platform_context
  -> 读取 common/design-and-prompt.md
  -> 只读取 platforms/<platform_id>.md
  -> 按条件读取 common/custom-product.md
  -> 读取 common/generation-workflow.md
  -> 选择工具并读取 tools/<tool>.md
  -> 预写三版提示词并生成
  -> 读取 common/delivery.md
  -> 重新核对已选平台文件中的交付清单
```

- [ ] Amazon 任务的加载集合必须是 `common/* + platforms/amazon.md + 当前工具适配器`，不得读取 `platforms/temu.md`。
- [ ] TEMU 任务的加载集合必须是 `common/* + platforms/temu.md + 当前工具适配器`，不得读取 `platforms/amazon.md`。
- [ ] 平台文件必须在三版提示词冻结前完整读取；交付前只核对同一平台文件，不允许临时切换平台。
- [ ] 工具选择与平台选择正交：Amazon 和 TEMU 都可使用 ImageGen 或 Seedream，工具适配器不得隐含平台规则。

### 5. 规则合并与优先级

- [ ] 使用以下固定优先级，避免“需求表最高”与“平台硬限制”互相冲突：
    1. 通用硬约束：产品真实性、输入门禁、安全与工具调用合同；
    2. 已选平台的硬性合规规则；
    3. 用户要求与需求表中的商品事实、交付目标和文案；两者冲突时阻塞确认；
    4. 已选平台的软性默认值；
    5. 通用设计默认值；
    6. 反推专用参考图得到的视觉候选。
- [ ] 平台规则统一标记等级：
    - `HARD/BLOCK`：违反时必须阻塞；
    - `REQUIRED`：生成提示词和交付检查必须体现；
    - `DEFAULT`：没有明确需求时采用；
    - `RECOMMENDED`：可被更高优先级的明确需求覆盖。
- [ ] 平台文件只能覆盖明确声明为“可平台覆盖”的通用字段，例如提示词前缀、交付类型、比例、语言、单位、主图限制和导出限制；不得覆盖通用工作流不变量。

### 6. 平台规范文件统一契约

每个平台文件使用相同结构，避免 `SKILL.md` 针对不同平台编写两套分支逻辑。

```yaml
---
platform_id: amazon
display_name: Amazon
marketplace_scope: [US]
aliases: [Amazon, 亚马逊, Amazon US, 美亚]
spec_version: 1
status: draft
verified_at: null
official_sources: []
---
```

- [ ] 两个平台文件必须包含相同章节：
    1. 适用范围与站点；
    2. 支持的交付类型及名称映射；
    3. 比例、像素、格式、大小等技术约束；
    4. 主图规范；
    5. 副图、详情页及平台专属模块规范；
    6. 文案语言、单位与本地化；
    7. 设计限制与合规限制；
    8. 提示词适配值；
    9. 交付检查清单；
    10. 阻塞条件。
- [ ] `Amazon` 文件负责 Amazon 专属交付类型，例如普通 A+、高级 A+ 及其映射；这些术语不得再出现在通用交付类型列表中。
- [ ] `TEMU` 文件只声明 TEMU 实际支持的交付类型和限制；未声明的 Amazon 专属类型不得自动映射成 TEMU 详情页。
- [ ] 所有会随平台政策变化的数值规则必须附官方来源、适用站点和 `verified_at`；无法从官方来源核实的规则标记为 `TODO-VERIFY`，不得作为 `HARD/BLOCK` 执行。
- [ ] 平台文件中不重复唯一 `edit target`、颜色配对、产品尺寸真实性、三版差异化、Subagent 串行等通用规则，只引用通用规则为前置合同。

### 7. 现有规范迁移表

| 当前耦合内容 | 目标位置 | 迁移要求 |
|---|---|---|
| manifest、输入图片分类、反推专用参考图、颜色配对 | `common/design-and-prompt.md` | 保持为跨平台不变量 |
| 三版规划、唯一 `edit target`、Subagent 串行、技术重试 | `common/generation-workflow.md` | 不允许平台覆盖 |
| 定制产品、系带、滚边、防滑底、面料细节 | `common/custom-product.md` | 保持业务通用规则 |
| 文件命名、哈希、直接保存、不中选、不看成图 | `common/delivery.md` | 保持工具与平台无关 |
| 固定前缀 `Amazon US E-commerce Product Imagery` | `platforms/amazon.md` | 从通用提示词模板移除 |
| `主图/副图/详情页/普通 A+/高级 A+` 的并列定义 | 平台文件 | Amazon 与 TEMU 分别声明自己的交付类型 |
| 主副图、详情页、A+ 的比例映射 | 平台文件 | 通用模板只接收已解析的 `target_ratio` |
| “符合北美/美国目标市场”“图片内不得出现中文” | 平台文件的本地化章节 | 与 `marketplace` 绑定，不作为全平台通用规则 |
| `inch` 优先 | 平台文件的单位策略 | 不再写入通用交付规则 |
| 主图能否有文字、是否白底、色块如何呈现 | 平台文件的主图章节 | 分平台核验，不再假定两平台相同 |
| 无依据绝对化、医疗功效、认证、未授权素材 | 通用合规基线 + 平台补充 | 通用文件保留底线，平台文件只补充更严格差异 |
| `imagegen.md` 中“TEMU 工作流” | `tools/imagegen.md` | 改为“当前电商图片工作流”，保留平台字段记录 |
| `seedream.md` 中“TEMU 产品目录/TEMU 产品图” | `tools/seedream.md` | 改为“当前任务根目录/当前产品实拍” |
| `temu_image_inspector` | 通用命名或兼容别名 | 优先改为 `commerce_image_inspector`；若外部配置暂不能同步，保留旧名兼容并注明其职责与平台无关 |
| `agents/openai.yaml` 的 TEMU / Amazon 展示文案 | 中性展示文案 | 不改 `$temu-img` 的兼容调用名 |

### 8. 通用提示词模板改造

- [ ] 从 `common/design-and-prompt.md` 删除固定平台值，改为由平台文件提供并在冻结提示词前解析：
    - `platform_prompt_prefix`
    - `platform_id`
    - `marketplace`
    - `deliverable_type`
    - `target_ratio`
    - `copy_language`
    - `unit_policy`
    - `main_image_policy`
    - `platform_compliance`
- [ ] 通用提示词继续保留 `【画面目标】`、`【产品输入】`、`【画面构成】`、`【颜色/面料】`、`【view_image 实际输入记录】`、`【文案】`、`【风格】`、`【版式/字体与配色】` 等跨平台字段。
- [ ] 发送给生成 Subagent 前必须把所有平台变量解析为最终值；提示词中不得残留 `{{variable}}`、候选比例、平台选择说明或另一个平台的术语。
- [ ] 同一图号三个 direct 必须冻结同一 `platform_id`、`marketplace`、交付类型、目标比例、文案语言和单位策略。
- [ ] 每次调用记录补充 `platform_id`、`marketplace`、`platform_spec_version` 和 `platform_spec_sha256`，便于中断恢复和结果追踪。

### 9. `SKILL.md` 重构任务

- [ ] 将标题和描述改为中性电商图片工作流，同时保留 front matter 中 `name: temu-img`。
- [ ] 在“开工前检查”最前面增加平台必填项和平台冲突检查。
- [ ] 新增“平台选择器”，只读取 `platforms/index.md` 并解析平台，不预读全部平台规范。
- [ ] 将当前固定的 Amazon/TEMU 交付类型描述改成“由已选平台规范声明”。
- [ ] 在设计步骤中明确：先冻结平台，再读取通用设计模块和唯一命中平台模块。
- [ ] 在首次生图前检查中增加平台规范版本、交付类型合法性、比例映射和本地化策略检查。
- [ ] 在报告完成前增加平台交付清单核对，且平台上下文必须与所有 direct 调用记录一致。
- [ ] 对平台缺失、冲突、不支持、交付类型不支持分别给出稳定错误码，不用自然语言模糊兜底。

### 10. 实施顺序

- [ ] Phase 0：保存现有行为基线，列出所有文件中的 `Amazon`、`TEMU`、`A+`、`北美`、`美国`、`inch`、平台比例及平台路径引用。
- [ ] Phase 1：创建 `common/`、`platforms/`、`tools/`，先复制文件并修正内部链接；在所有新路径可读前不删除旧文件。
- [ ] Phase 2：实现 `platforms/index.md`、平台解析门禁与 `_platform_context.json`，但暂时让两个平台文件复现现有行为，先保证无回归。
- [ ] Phase 3：从 `design-and-prompt.md`、`delivery.md`、工具适配器中抽离平台专属内容，写入 `amazon.md` 与 `temu.md`。
- [ ] Phase 4：逐条核验 Amazon 与 TEMU 官方规范，补齐来源、站点范围、验证日期及规则等级；不把未经核验的当前经验直接升级为硬规则。
- [ ] Phase 5：将 `temu_image_inspector` 与工具文档中的平台耦合命名中性化，并保留必要兼容层。
- [ ] Phase 6：更新所有 Markdown 链接、脚本路径、测试、`agents/openai.yaml` 和 README；确认 Windows 中文路径行为不受影响。
- [ ] Phase 7：删除或改为迁移说明的旧路径文件，确保仓库中每条规则只有一个权威来源。
- [ ] 每个 Phase 单独提交，且每个提交结束时 Skill 都必须处于可读、无断链状态；不产生“引用新路径但文件尚不存在”的中间提交。

### 11. 验收测试矩阵

| 场景 | 预期结果 |
|---|---|
| 用户和需求表均明确 Amazon，普通主副图任务 | 只读取 common、amazon 和当前工具文件 |
| 用户和需求表均明确 TEMU，详情页任务 | 只读取 common、temu 和当前工具文件 |
| 用户写 Amazon、需求表写 TEMU | `PLATFORM_CONFLICT`，生图前阻塞 |
| 用户和需求表都未写平台 | `PLATFORM_REQUIRED`，不得默认 Amazon |
| 平台为 eBay 等未注册值 | `UNSUPPORTED_PLATFORM` |
| TEMU 任务请求平台文件未声明的 A+ 类型 | `UNSUPPORTED_DELIVERABLE`，不得静默转成详情页 |
| Session 中断后恢复，平台和规范哈希未变 | 复用 `_platform_context.json` 并从缺失 direct 继续 |
| Session 恢复时平台或规范哈希变化 | 阻塞并重新规划，不复用旧提示词 |
| Amazon + ImageGen 与 Amazon + Seedream | 平台规则一致，只有工具调用合同不同 |
| TEMU + ImageGen 与 TEMU + Seedream | 平台规则一致，只有工具调用合同不同 |
| 扫描 `references/common/` | 不应出现 Amazon/TEMU 专属前缀、A+、固定站点、固定单位或平台比例 |
| 扫描调用记录 | 每条记录均可追溯平台、站点、规范版本和规范哈希 |

### 12. 自动化校验

- [ ] 新增轻量静态校验脚本，例如 `scripts/validate_platform_architecture.py`：
    - 校验注册表中的平台文件均存在；
    - 校验平台 front matter 必填字段完整；
    - 校验两个平台文件章节结构一致；
    - 校验 `common/` 不包含受控的平台专属词；
    - 校验所有相对链接有效；
    - 校验 `SKILL.md` 不直接硬编码平台比例、A+ 类型或固定提示词前缀。
- [ ] 为平台路由添加最小测试用例，不需要调用生图工具；测试只验证解析、加载集合、错误码、优先级和上下文恢复。
- [ ] 保留现有 Seedream 脚本测试，平台重构不得修改 API 请求与文件保存语义。

### 13. 完成标准

- [ ] `SKILL.md` 成为纯路由与编排入口，不再同时承载 Amazon/TEMU 具体规范。
- [ ] 所有跨平台不变量只有一个通用规则源。
- [ ] 所有 Amazon 专属规则只存在于 `platforms/amazon.md`。
- [ ] 所有 TEMU 专属规则只存在于 `platforms/temu.md`。
- [ ] 任一任务只加载一个平台文件，且平台上下文可持久化、可恢复、可追踪。
- [ ] 平台技术限制和政策规则均有适用站点、官方来源、验证日期和规则等级。
- [ ] 通用工作流、三版串行、产品真实性、色块配对、工具调用及直接保存行为无回归。
- [ ] 全部静态校验与平台路由测试通过后，再开始在真实 Amazon 与 TEMU 任务上分别做一套冒烟测试。
