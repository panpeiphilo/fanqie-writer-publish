---
name: fanqie-writer-publish
description: 把本地章节 txt 批量搬运到番茄小说作家后台的草稿箱，并可新建/切换分卷（ProseMirror 正文注入、受控 input 填章号、幂等跳过、断点续传）。当用户需要把小说章节上传/导入/搬运到番茄作家后台、批量建草稿、新建分卷或把章节归到指定卷、核对后台章节状态，或问「怎么把稿子批量放到番茄后台」「上传到草稿箱」「帮我建卷」时使用。仅写草稿，不点发布。
agent_created: true
---

# 番茄作家后台批量上传与分卷

## 适用场景

- 手上有成百章本地稿（单章 txt 目录，或一个合并的发布版 txt），要搬进番茄作家后台
- 网文作者日更排期，需要把未来几天/几周的章节提前放进草稿箱
- 长篇要分卷，后台卷还没建齐，或章节归错了卷
- 后台章节状态对不上账，要核对「哪些已发布、哪些排了定时、哪些还在草稿箱」

不适用：改正文内容、调排版、发布、定时发布设置。这些交给人工在后台做。

## 前置条件

1. **本机有 Chrome**（路径找不到时用环境变量 `CHROME_PATH` 指过去）
2. **已登录 fanqienovel.com**，且登录态落在持久 profile 里
   - 默认 profile：`~/.fanqie-profile`（可用 `FANQIE_PROFILE` 覆盖）
   - 首次使用：`python scripts/fanqie_upload_cdp.py ... --headed` 打开有头浏览器，人工扫码一次
3. **知道 bookId**：章节管理页 URL 里那串数字
   `https://fanqienovel.com/main/writer/chapter-manage/7682830798759676952`
4. **章节文件格式**：首行为 `第N章 标题`，其后每行一个自然段，空行会被忽略

> **通道说明**：优先用**纯 CDP**（`*_cdp.py` 系列，零依赖，本机实测可用）。
> 老的 `fanqie_upload.py` 依赖 agent-browser，在部分 Windows/RDP 环境中会
> `Chrome exited early (exit=0)` 或进程被 SIGTERM，属于环境问题，不是脚本 bug。
> 见 `references/troubleshooting.md` §8。

## 工作流

### 步骤 0：分卷盘点（要分卷就先做这步）

```bash
python scripts/fanqie_volume.py --book-id <bookId> --list
```

读的是**章节管理页的卷筛选下拉**（服务端数据）。别用编辑页弹窗里的列表判断——
本地未提交的新建项和已落库的卷长得一模一样。

建卷：

```bash
python scripts/fanqie_volume.py --book-id <bookId> --create 合伙人
```

只给卷名，**不要带「第N卷：」前缀**（后台自动编号，前缀是只读的）。
建完会再读一次服务端列表确认。

> **平台硬限制**：不允许两个空卷并存。新建一卷后立刻再建下一卷会返回
> `-4054 暂不支持创建多个无章节的分卷`。要么先给上一个空卷挂一章，要么按发布节奏
> 到点再建。详见 `references/backend-dom.md` §8.5。

### 步骤 1：先体检，确认后台停在哪一章

```bash
python scripts/check_status.py --book-id <bookId> --last 15
```

输出各章的字数、状态（已发布/待发布/草稿）、定时时间。**先看清楚再上传**——
如果列表里有 `待发布` + 未来时间，那是已排定的定时发布，不是「没发出去」。

### 步骤 2：干跑，只看解析结果

```bash
python scripts/fanqie_upload_cdp.py --book-id <bookId> --from 148 --to 152 \
    --dir ./chapters --dry-run
```

确认章号、标题、段落数、字数都对得上，再真跑。

### 步骤 3：真跑，小批量验证

```bash
python scripts/fanqie_upload_cdp.py --book-id <bookId> --from 148 --to 149 \
    --dir "03-发布版" --volume "第三卷：中层管理" --interval 45
```

`--volume` 建议显式给。编辑页的默认卷继承自「章节管理页当前选中的卷」，
不写就可能全落进同一卷里。

跑完让用户去草稿箱抽查首尾各一章：**分段是否正确、标点是否完整、有没有串章**。

### 步骤 4：确认无误后放量

```bash
python scripts/fanqie_upload_cdp.py --book-id <bookId> --from 150 --to 165 \
    --dir ./chapters --volume "第三卷：中层管理" --interval 60
```

每次不超过 15 章，中间停一次。脚本会读草稿箱已有章号自动跳过（`--force` 可强制重传）。

### 步骤 5：归属修正（只在确认卷错了时用）

```bash
python scripts/fanqie_volume.py --book-id <bookId> --assign 148="第三卷：中层管理"
```

会打开该草稿 → 选卷 → 点「确定」→ 存草稿 → 回读页头卷名。

## 四条硬约束

1. **只点「存草稿」，永不点「下一步」**。「下一步」会进入发布流程（立即/定时发布），
   发布不可撤销，且直接影响全勤、星火等奖项的时间点判定。发布权留给作者。
2. **幂等优先**。上传前先读后台已有章号，已存在的跳过。后台不阻止重复章号，
   重传会造成读者看到两章同号，删除还要走审核。除非确认过，不要加 `--force`。
3. **节流**。每章间隔 ≥40 秒（批量 60 秒），单次 ≤15 章，单章正文 3000-4500 字。
   平台明确会监测「短期内高频创建/发布章节」。
4. **一次进程干完**。Chrome 随脚本退出而结束，**不能跨脚本调用保持浏览器会话**。
   批量上传要在同一条命令里跑完，别指望「先开浏览器，再另开一个脚本连上去」。

## 关键技术点

### 正文：ProseMirror

- 直接改 `innerHTML` → React 内部状态不更新，保存后是空章
- 改 `value` → contenteditable 没有 value，无效
- 正确做法 → 先真实点一下编辑器，再 `document.execCommand('insertText', false, paras.join('\n'))`，
  PM 会把每个 `\n` 转成独立 `<p>`
- **平台 p 数 = 本地段数 + 1**（末尾占位空段），不占字数，不要去删
- 校验用「p ≥ 段数-1」且「净字数差 ≤30」，别用严格相等

### 章号 / 标题：受控 input

用「点击 + Ctrl+A + insertText」会丢焦点，章号填不进去 → 存成「第 章 XXX」。

必须用原生 setter：

```js
const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
s.call(e, '148');
e.dispatchEvent(new Event('input',  {bubbles: true}));
e.dispatchEvent(new Event('change', {bubbles: true}));
e.value   // 回读校验
```

### React 元素点击

`element.click()` 对番茄后台无效，要用 `Input.dispatchMouseEvent` 派发真实
mousedown/mouseup。`cdp_client.py` 的 `click_at()` 已封装。

详细 DOM、选择器、分卷弹窗结构、版本冲突弹窗处理见 `references/backend-dom.md`。

平台规则、发文额度、全勤字数线、节流参数依据见 `references/risk-control.md`。

掉登录、扫码扫不出、编辑器未渲染、段落数不符、建卷 -4054、Chrome 起不来等故障见
`references/troubleshooting.md`。

## 脚本

| 脚本 | 作用 |
|---|---|
| `scripts/cdp_client.py` | 零依赖 CDP 客户端：起 Chrome、连标签页、执行 JS、派发真实鼠标/键盘事件 |
| `scripts/fanqie_upload_cdp.py` | **主推**：解析章节 → 读草稿箱已有章号 → 逐章新建草稿 → 填章号/标题/正文 → 切卷 → 存 → 回读校验 |
| `scripts/fanqie_volume.py` | 分卷：`--list` 读服务端卷列表 / `--create` 建卷 / `--assign` 改章归属 |
| `scripts/fanqie_upload.py` | 旧版（依赖 agent-browser），环境可用时仍可使用 |
| `scripts/check_status.py` | 抓后台章节状态，可导出 CSV，可与本地目录比对字数 |

`fanqie_upload_cdp.py` 主要参数：

| 参数 | 说明 |
|---|---|
| `--book-id` | 必填，作品 ID |
| `--from` / `--to` | 章节范围（闭区间） |
| `--dir` | 单章 txt 目录（文件名 `第148章_标题.txt`） |
| `--file` | 合并 txt，按 `第N章 标题` 自动切章 |
| `--volume` | 目标分卷全名，如 `"第三卷：中层管理"` |
| `--interval` | 每章间隔秒，默认 45 |
| `--dry-run` | 只解析不写入 |
| `--force` | 跳过「后台已存在」检查（慎用） |
| `--headed` | 开有头浏览器（首次登录用） |

## 交付时的表达方式

上传完成后主动给用户这张表，而不是只说「传完了」：

| 章 | 标题 | 平台字数 | 卷 | 状态 | 定时 |
|---|---|---|---|---|---|

并明确说明：**草稿箱里的章节还没有发布时间，需要你在后台逐篇点「下一步」设时间**。
顺带提醒下一个可用的发布日，避免和已有的定时撞车。
