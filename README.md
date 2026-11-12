# fanqie-writer-publish

把本地小说章节批量搬进**番茄小说作家后台草稿箱**的自动化工具，打包为可直接安装的 Agent Skill。

> 上传到草稿箱为止。发布、定时发布权限留给作者本人。

## 它解决什么

写到两百章之后，每天最烦的不是码字，是**复制粘贴**：

- 打开后台 → 新建章节 → 填章号 → 填标题 → 粘贴正文 → 检查有没有吞段 → 存草稿
- 一章两次点击、三次粘贴，一天两章，一年 700 次
- 粘贴长文经常整章挤成一段，或者空行全丢，改起来比重打还慢

这个 skill 把这一串动作压成一条命令，并且**逐章校验段落数**——吞段会当场报错停下，不会静默存进一个残章。

## 特性

| 特性 | 说明 |
|---|---|
| **ProseMirror 正确注入** | 走 `execCommand('insertText')`，每段生成独立 `<p>`，不是塞 HTML 假分段 |
| **幂等** | 上传前读后台已有章号，已存在的自动跳过，不会造出两个「第139章」 |
| **断点续传** | 每章成功写 state 文件，中断后重跑从断点继续 |
| **逐章校验** | 段落数必须一致，平台字数偏差超阈值即停 |
| **只写草稿** | 永不点「下一步」，不触发发布审核，不影响全勤/星火的时间点 |
| **状态核对** | 附带脚本抓后台章节状态，可导出 CSV，可与本地字数对账 |

## 安装

```bash
# 1. 安装浏览器自动化依赖
npm install -g agent-browser
agent-browser install

# 2. 验证 Node 真的能跑（不输出 ok 就是坏的）
node -e "console.log('ok')"

# 3. 把本目录放进 skills 目录
#    WorkBuddy：~/.workbuddy/skills/fanqie-writer-publish
#    Claude Code：~/.claude/skills/fanqie-writer-publish
```

## 快速开始

```bash
# 0. 先登录一次（会弹出浏览器窗口，扫码或短信验证码）
agent-browser open https://fanqienovel.com/main/writer/login --headed

# 1. 体检：确认后台停在第几章、有没有已排的定时
python scripts/check_status.py --book-id 7682830798759676952 --last 15

# 2. 干跑：只解析，不写入
python scripts/fanqie_upload.py --book-id 7682830798759676952 \
    --from 139 --to 143 --file "./《书名》发布版.txt" --dry-run

# 3. 真跑（小批量）
python scripts/fanqie_upload.py --book-id 7682830798759676952 \
    --from 139 --to 143 --file "./《书名》发布版.txt" --interval 40

# 4. 放量
python scripts/fanqie_upload.py --book-id 7682830798759676952 \
    --from 144 --to 180 --dir ./chapters --interval 60
```

`book-id` 在章节管理页 URL 里：
`https://fanqienovel.com/main/writer/chapter-manage/**7682830798759676952**`

## 章节文件格式

单章文件（`--dir`），首行是章名，其后每行一个自然段：

```
第139章 阿福觉醒

天亮了。

阿福没上炕。
```

合并文件（`--file`）就是这些内容首尾相接，脚本按 `^第\d+章` 自动切。

空行会被忽略，全角空格建议先清洗掉。

## 工作原理

番茄的章节编辑器是 **ProseMirror**。这决定了只有一条路走得通：

```js
const el = document.querySelectorAll('.ProseMirror')[0];  // 页面上有 5 个，正文是第 0 个
el.focus();
document.execCommand('selectAll');
document.execCommand('delete');
document.execCommand('insertText', false, paras.join('\n'));
el.querySelectorAll('p').length;   // 应等于段落数
```

- 直接 `innerHTML = ...` → React 状态不更新，存进去是空章
- `\n` 交给 ProseMirror 处理 → 每段生成独立 `<p>`，正好是小说要的分段

细节（选择器、按钮文案、版本冲突弹窗、id 关系）见 [`references/backend-dom.md`](references/backend-dom.md)。

## 已知限制

- **平台改版会失效**。class 名是编译生成的，但表结构和按钮文案相对稳定，脚本尽量依赖后者。
- **需要手动登录一次**。番茄没有可用的长期 token 方案，扫码有效期约 2 分钟。
- **不处理定时发布**。这是刻意的：发布不可撤销，且直接决定全勤/星火的时间点。
- **不生成正文**。只做「本地 txt → 后台编辑器」的搬运。

## 风险声明

平台会监测「短期内高频创建作品、高频发布章节或发布超长篇幅内容」。本项目默认节流（每章 40-60 秒、单次 ≤15 章），但**使用自动化工具的账号风险由使用者自行承担**。上线前请阅读番茄作家平台的最新公告与协议。

## 目录结构

```
fanqie-writer-publish/
├── SKILL.md                       # Agent Skill 入口（工作流 + 硬约束）
├── scripts/
│   ├── fanqie_upload.py           # 主流程
│   └── check_status.py            # 状态核对
└── references/
    ├── backend-dom.md             # 后台 DOM 结构、选择器、注入方法
    ├── risk-control.md            # 平台规则、发文额度、节流依据
    └── troubleshooting.md         # 12 类故障排查
```

## License

MIT
