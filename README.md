# fanqie-writer-publish

把本地小说章节批量搬进**番茄小说作家后台草稿箱**、并按卷归档的自动化工具，打包为可直接安装的 Agent Skill。

> 上传到草稿箱为止。发布、定时发布权限留给作者本人。

## 它解决什么

写到两百章之后，每天最烦的不是码字，是**复制粘贴**：

- 打开后台 → 新建章节 → 填章号 → 填标题 → 粘贴正文 → 检查有没有吞段 → 存草稿
- 一章两次点击、三次粘贴，一天两章，一年 700 次
- 粘贴长文经常整章挤成一段，或者空行全丢，改起来比重打还慢
- 长篇要分卷，后台卷还没建，或者新章全落进了默认那一卷

这个 skill 把这一串动作压成一条命令，并且**逐章校验段落数与字数**——吞段会当场报错停下，不会静默存进一个残章。

## 特性

| 特性 | 说明 |
|---|---|
| **ProseMirror 正确注入** | 走 `execCommand('insertText')`，每段生成独立 `<p>`，不是塞 HTML 假分段 |
| **受控 input 正确填写** | 章号/标题用原生 setter + input 事件，避开 headless 焦点丢失导致的「第 章 XXX」 |
| **幂等** | 上传前读草稿箱已有章号，已存在的自动跳过，不会造出两个「第139章」 |
| **逐章回读校验** | 每章存完回读草稿箱确认章号出现，未见即停，不静默放过 |
| **分卷** | `--list` 读服务端卷列表 / `--create` 建卷（自动编号）/ `--assign` 改章归属 |
| **只写草稿** | 永不点「下一步」，不触发发布审核，不影响全勤/星火的时间点 |
| **状态核对** | 附带脚本抓后台章节状态，可导出 CSV，可与本地字数对账 |
| **零依赖** | 只用 Python 标准库自带 CDP 客户端，不需要装 Playwright / Puppeteer / agent-browser |

## 安装

```bash
# 只需要 Python 3.8+ 和一个本机 Chrome
# 把本目录放进 skills 目录：
#   WorkBuddy：~/.workbuddy/skills/fanqie-writer-publish
#   Claude Code：~/.claude/skills/fanqie-writer-publish
```

## 配置（一次配好，之后不用再带环境变量）

```bash
cp config.example.json config.json
# 打开 config.json，改这两项就够：
#   profile  → 登录态所在目录（默认 ~/.fanqie-profile）
#   book_id  → 作品 ID
python scripts/fanqie_config.py     # 自检：生效值 + 来源 + profile 是否可用
```

自检输出长这样，一眼能看出 profile 最终是从哪来的：

```
配置文件   : D:\Data\WorkBuddy\fanqie-writer-publish\config.json
profile   : D:/Data/WorkBuddy/.fanqie-profile        [config.json]
book_id   : 7682830798759676952                      [config.json]
chrome    : C:\Program Files\...\chrome.exe  (自动探测) [默认]
✅ profile 可用：D:/Data/WorkBuddy/.fanqie-profile
```

取值优先级：**命令行参数 > 环境变量 > `config.json` > 自动发现 > 内置默认**。

- `config.json` 已在 `.gitignore` 里，不会被提交
- **profile 会自动找**：没配或默认位置为空时，会去 `<当前目录>/.fanqie-profile`、`<上级目录>/.fanqie-profile`、`~/.fanqie-profile` 里挑一个带 Cookies 的用。登录态放在书稿目录旁边也能直接跑，但建议还是显式写进配置，免得换个目录跑就失效
- 不想写配置文件也可以只用环境变量：

```bash
export FANQIE_PROFILE="$HOME/.fanqie-profile"
export CHROME_PATH="/path/to/chrome"          # Windows Git Bash 同理
export FANQIE_BOOK_ID="7682830798759676952"
```

> 旧版脚本 `fanqie_upload.py` 需要 `npm install -g agent-browser`。它在一部分
> Windows / RDP 环境里起不来（`Chrome exited early (exit=0)`），所以主推纯 CDP 版本。
> 见 `references/troubleshooting.md` §8。

## 快速开始

```bash
# 0. 首次：开有头浏览器登录一次（扫码约 2 分钟有效）
python scripts/fanqie_upload_cdp.py --from 148 --to 148 --dir ./chapters --headed

# 1. 体检：后台停在第几章、有没有已排的定时、分了几卷
python scripts/check_status.py --book-id 7682830798759676952 --last 15
python scripts/fanqie_volume.py --list

# 2. 建卷（只给卷名，前缀「第N卷：」由后台自动编号）
python scripts/fanqie_volume.py --create 合伙人

# 3. 干跑：只解析，不写入
python scripts/fanqie_upload_cdp.py --from 148 --to 152 --dir ./chapters --dry-run

# 4. 真跑（小批量，显式指定卷）
python scripts/fanqie_upload_cdp.py --from 148 --to 149 --dir ./chapters \
    --volume "第三卷：中层管理" --interval 45

# 5. 放量
python scripts/fanqie_upload_cdp.py --from 150 --to 165 --dir ./chapters \
    --volume "第三卷：中层管理" --interval 60
```

上面省了 `--book-id`，因为配置里已经写好了。没配的话照旧加
`--book-id 7682830798759676952`（章节管理页 URL 里那串数字）。

## 章节文件格式

单章文件（`--dir`），文件名 `第148章_标题.txt`，首行是章名，其后每行一个自然段：

```
第148章 幕末·双邀

天亮了。

阿福没上炕。
```

合并文件（`--file`）就是这些内容首尾相接，脚本按 `^第\d+章` 自动切。

空行会被忽略，全角空格建议先清洗掉。

## 工作原理

番茄的章节编辑器是 **ProseMirror**。这决定了正文只有一条路走得通：

```js
const el = document.querySelectorAll('.ProseMirror')[0];  // 页面上有 5 个，正文是第 0 个
el.focus();
document.execCommand('selectAll');
document.execCommand('delete');
document.execCommand('insertText', false, paras.join('\n'));
el.querySelectorAll('p').length;   // ≈ 段落数 + 1
```

- 直接 `innerHTML = ...` → React 状态不更新，存进去是空章
- `\n` 交给 ProseMirror 处理 → 每段生成独立 `<p>`，正好是小说要的分段
- 末尾会多一个占位空 `<p>`，**不占字数**，不要去删

章号和标题是 React 受控 input，必须用原生 setter：

```js
const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
s.call(e, '148');
e.dispatchEvent(new Event('input', {bubbles: true}));
e.dispatchEvent(new Event('change', {bubbles: true}));
```

而所有点击都要走 CDP 的 `Input.dispatchMouseEvent`——`element.click()` 对这套前端无效。

细节（选择器、分卷弹窗结构、草稿箱表、版本冲突弹窗、id 关系）见
[`references/backend-dom.md`](references/backend-dom.md)。

## 分卷的两个坑

1. **建卷只有一处入口**：章节编辑页顶部点卷名 → 弹窗底部「新建分卷」→ 输卷名 →
   点**绿勾**。按 Enter、点底部「确定」都无效（后者在新建态是灰的）。
2. **不允许两个空卷并存**：新建一卷后立刻再建下一卷，接口返回
   `-4054 暂不支持创建多个无章节的分卷`。要么先给上一卷挂一章，要么按发布节奏到点再建。

判定卷有没有真的建上，只看**章节管理页的卷筛选下拉**（服务端数据），不要看弹窗里的列表。

## 已知限制

- **平台改版会失效**。class 名是编译生成的，但表结构和按钮文案相对稳定，脚本尽量依赖后者。
- **需要手动登录一次**。番茄没有可用的长期 token 方案，扫码有效期约 2 分钟。
- **不处理定时发布**。这是刻意的：发布不可撤销，且直接决定全勤/星火的时间点。
- **不生成正文**。只做「本地 txt → 后台编辑器」的搬运。
- **不能跨进程保持浏览器会话**。Chrome 随脚本退出而结束，批量上传要在同一条命令里跑完。

## 风险声明

平台会监测「短期内高频创建作品、高频发布章节或发布超长篇幅内容」。本项目默认节流（每章 40-60 秒、单次 ≤15 章），但**使用自动化工具的账号风险由使用者自行承担**。上线前请阅读番茄作家平台的最新公告与协议。

## 目录结构

```
fanqie-writer-publish/
├── SKILL.md                       # Agent Skill 入口（工作流 + 硬约束）
├── config.example.json            # 配置模板（复制成 config.json 用）
├── scripts/
│   ├── fanqie_config.py           # 配置读取（profile / bookId / chrome / 端口）+ 自检
│   ├── cdp_client.py              # 零依赖 CDP 客户端（起 Chrome / 连标签页 / 派发真实事件）
│   ├── fanqie_upload_cdp.py       # 主流程（纯 CDP 通道）
│   ├── fanqie_volume.py           # 分卷：查 / 建 / 改归属
│   ├── fanqie_upload.py           # 旧版（依赖 agent-browser）
│   └── check_status.py            # 状态核对
└── references/
    ├── backend-dom.md             # 后台 DOM 结构、选择器、分卷弹窗、注入方法
    ├── risk-control.md            # 平台规则、发文额度、节流依据
    └── troubleshooting.md         # 15 类故障排查
```

## License

MIT
