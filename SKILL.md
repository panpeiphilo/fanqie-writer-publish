---
name: fanqie-writer-publish
description: 把本地章节 txt 批量搬运到番茄小说作家后台的草稿箱（浏览器自动化，ProseMirror 正文注入、幂等跳过、断点续传）。当用户需要把小说章节上传/导入/搬运到番茄作家后台、批量建草稿、核对后台章节状态，或问「怎么把稿子批量放到番茄后台」「上传到草稿箱」时使用。仅写草稿，不点发布。
agent_created: true
---

# 番茄作家后台批量上传

## 适用场景

- 手上有成百章本地稿（单章 txt 目录，或一个合并的发布版 txt），要搬进番茄作家后台
- 网文作者日更排期，需要把未来几天/几周的章节提前放进草稿箱
- 后台章节状态对不上账，要核对「哪些已发布、哪些排了定时、哪些还在草稿箱」

不适用：改正文内容、调排版、发布、定时发布设置。这些交给人工在后台做。

## 前置条件

1. **agent-browser 可用**
   ```bash
   npm install -g agent-browser && agent-browser install
   node -e "console.log('ok')"   # 必须真的输出 ok，否则内部 spawn 会崩
   ```
2. **已在 agent-browser 会话里登录 fanqienovel.com**
   首次用 `--headed` 打开登录页，让用户扫码或填短信验证码。登录态存在于 daemon 的 profile 中，`close` 之后可能要重登。
3. **知道 bookId**：就是章节管理页 URL 里那串数字
   `https://fanqienovel.com/main/writer/chapter-manage/7682830798759676952`
4. **章节文件格式**：首行为 `第N章 标题`，其后每行一个自然段，空行会被忽略

## 工作流

### 步骤 1：先体检，确认后台停在哪一章

```bash
python scripts/check_status.py --book-id <bookId> --last 15
```

输出各章的字数、状态（已发布/待发布/草稿）、定时时间。**先看清楚再上传**——如果列表里有 `待发布` + 未来时间，那是已排定的定时发布，不是「没发出去」。

### 步骤 2：干跑，只看解析结果

```bash
python scripts/fanqie_upload.py --book-id <bookId> --from 139 --to 143 \
    --file ./《书名》发布版.txt --dry-run
```

确认章号、标题、段落数、字数都对得上，再真跑。

### 步骤 3：真跑，小批量验证

```bash
python scripts/fanqie_upload.py --book-id <bookId> --from 139 --to 143 \
    --file ./《书名》发布版.txt --interval 40
```

跑完让用户去草稿箱抽查首尾各一章：**分段是否正确、标点是否完整、有没有串章**。

### 步骤 4：确认无误后放量

```bash
python scripts/fanqie_upload.py --book-id <bookId> --from 144 --to 180 \
    --dir ./chapters --interval 60
```

每次不超过 15 章，中间停一次。脚本会跳过后台已存在的章号，中断后重跑自动接着来。

## 三条硬约束

1. **只点「存草稿」，永不点「下一步」**。「下一步」会进入发布流程（立即/定时发布），发布不可撤销，且直接影响全勤、星火等奖项的时间点判定。发布权留给作者。
2. **幂等优先**。上传前先读后台已有章号，已存在的跳过。后台不阻止重复章号，重传会造成读者看到两章同号，删除还要走审核。除非确认过，不要加 `--force`。
3. **节流**。每章间隔 ≥40 秒（批量 60 秒），单次 ≤15 章，单章正文 3000-4500 字。平台明确会监测「短期内高频创建/发布章节」。

## 关键技术点

正文编辑器是 **ProseMirror**，这是整个流程唯一容易翻车的地方：

- 直接改 `innerHTML` → React 内部状态不更新，保存后是空章
- 正确做法 → `document.execCommand('insertText', false, paras.join('\n'))`，PM 会把每个 `\n` 转成独立 `<p>`
- 写入后立刻用 `el.querySelectorAll('p').length` 对照源段落数，不符就停

详细 DOM 结构、选择器、版本冲突弹窗处理见 `references/backend-dom.md`。

平台规则、发文额度、全勤字数线、节流参数依据见 `references/risk-control.md`。

掉登录、扫码扫不出、编辑器未渲染、段落数不符等故障见 `references/troubleshooting.md`。

## 脚本

| 脚本 | 作用 |
|---|---|
| `scripts/fanqie_upload.py` | 主流程：解析章节 → 读后台已有章号 → 逐章新建草稿 → 校验 → 落盘断点 |
| `scripts/check_status.py` | 抓后台章节状态，可导出 CSV，可与本地目录比对字数 |

`fanqie_upload.py` 主要参数：

| 参数 | 说明 |
|---|---|
| `--book-id` | 必填，作品 ID |
| `--from` / `--to` | 章节范围（闭区间） |
| `--file` | 合并 txt，按 `第N章 标题` 自动切章 |
| `--dir` | 单章 txt 目录 |
| `--interval` | 每章间隔秒，默认 45 |
| `--state` | 断点文件，默认 `.fanqie_upload_state.json` |
| `--dry-run` | 只解析不写入 |
| `--force` | 跳过「后台已存在」检查（慎用） |

## 交付时的表达方式

上传完成后主动给用户这张表，而不是只说「传完了」：

| 章 | 标题 | 平台字数 | 状态 | 定时 |
|---|---|---|---|---|

并明确说明：**草稿箱里的章节还没有发布时间，需要你在后台逐篇点「下一步」设时间**。顺带提醒下一个可用的发布日，避免和已有的定时撞车。
