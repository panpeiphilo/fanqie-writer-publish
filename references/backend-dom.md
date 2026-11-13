# 番茄作家后台 DOM 结构（实测记录）

> 抓取时间：2026-11。平台改版随时可能失效，失效时先用 `snapshot` 重新摸一遍，再回来更新本文。

## 1. 页面入口

| 页面 | URL |
|---|---|
| 章节管理 | `https://fanqienovel.com/main/writer/chapter-manage/{bookId}` |
| 作品详情（带 `?type=1` 的变体） | `https://fanqienovel.com/main/writer/chapter-manage/{bookId}&{书名}?type=1` |
| 章节预览（只读） | `https://fanqienovel.com/main/writer/preview/{bookId}&{chapterId}` |
| 新建/编辑草稿 | `https://fanqienovel.com/main/writer/{bookId}/publish/{draftId}?enter_from=newdraft` |
| 登录页 | `https://fanqienovel.com/main/writer/login` |

`bookId` 就在章节管理页 URL 里，是一串纯数字（19 位左右）。

## 2. 章节管理页

顶部两个 tab：

```html
<div role="tab">章节管理</div>
<div role="tab">草稿箱</div>
```

**关键差异：**

| tab | 主按钮 | 说明 |
|---|---|---|
| 章节管理 | `新建章节` | 打开的是「直接写新章」流程，会走发布 |
| 草稿箱 | `新建草稿` | 打开的是草稿编辑器，只存草稿 |

要静默灌稿，必须**先点「草稿箱」tab**，再点「新建草稿」。停在「章节管理」tab 上永远找不到「新建草稿」按钮。

列表表头与列序（`td` 顺序）：

```
章节名称 | 字数 | 错别字 | 审核状态 | 发布时间 | 操作
```

`审核状态` 可能是：`已发布`、`待发布`（已设定时时间，到点自动发）、`审核中`、`未通过`。
`待发布` 的行会显示 `2026-11-16 07:05` 这类**未来时间**，那就是定时发布时间。

草稿箱列表列序不同：`章名 | 字数 | 时间（相对，如「20秒前」）`。

## 3. 编辑页

URL 形如 `/main/writer/{bookId}/publish/{draftId}?enter_from=newdraft`。

### 3.1 字段

| 字段 | 选择器 | 备注 |
|---|---|---|
| 章节序号 | `input.byte-input`（class 含 `serial-input`） | 只填数字，如 `139` |
| 章节标题 | `input[placeholder="请输入标题"]` | 只填标题，**不含「第N章」** |
| 正文 | `.ProseMirror`（页面上有 5 个，正文是**第 0 个**） | contenteditable |
| 作者有话说 | 第 1-2 个 `.ProseMirror` | 不要碰 |
| 人物设定 / 大纲等侧栏 | 其余 `.ProseMirror` | 不要碰 |

页头实时显示 `正文字数 N`，保存后显示 `已保存` 或 `已保存到云端`。这个 N 是校验基准。

### 3.2 正文注入（核心）

正文是 **ProseMirror**，不是普通 textarea。

- **直接改 `innerHTML` 无效**：React/PM 内部状态不会更新，点保存会存成空章。
- **`value` 属性对 contenteditable 无意义**。
- **正确做法**：`document.execCommand('insertText', false, text)`，其中 `text` 用 `\n` 连接各段。

实测行为：PM 会把每个 `\n` 变成**独立 `<p>` 元素**，正好对应小说的自然段。

```js
const el = document.querySelectorAll('.ProseMirror')[0];
el.focus();
document.execCommand('selectAll');
document.execCommand('delete');          // 清空已有内容
document.execCommand('insertText', false, paras.join('\n'));
el.querySelectorAll('p').length          // 应等于 paras.length
```

7,000 字约 2-3 秒完成，不会截断。写入后立刻用 `p` 数量自检，数量不符说明 PM 解析异常（常见于段落里有全角空格或零宽字符）。

### 3.3 按钮

| 按钮文案 | 作用 |
|---|---|
| `存草稿` | 只保存，不进发布队列 |
| `下一步` | 进入发布设置（立即发布 / 定时发布）→ **会进入发布流程，自动化不要点** |
| `继续编辑本地` | 版本冲突弹窗里的按钮，保留当前编辑器内容 |

保存成功后页面**不跳转**，只在页头显示 `已保存`。所以不能靠 URL 变化判断成功，必须等文本出现。

### 3.4 版本冲突弹窗

标题「版本冲突提示 — 检测到有2个版本冲突，请选择要保留并继续编辑的版本。」

两个按钮：`选择云端版本` / `继续编辑本地`。

出现原因：同一草稿在多个端（内置浏览器、另一个窗口、自动化）被编辑，或新建草稿时复用了历史空草稿。

**处理**：点 `继续编辑本地`，保留刚写入的内容。脚本里就是找这个按钮并 click。

### 3.5 id 关系

- 新建草稿时分配的 `draftId`，在点「下一步」提交后**直接变成章节 id**。
- 所以 `preview/{bookId}&{id}` 可以直接预览草稿内容 —— 这是核对是否串章最快的方式。

## 4. 登录态

- 首页未登录会有 `登录` / `注册` 文本；已登录显示作者笔名。
- 登录弹窗三选一：`验证码登录`（手机号+短信）/ `扫码登录` / `密码登录`。
- 扫码二维码是页面里的 `<img src="data:image/png;base64,...">`，原图 512×512，**有效期约 2 分钟**。
- 登录态存在 agent-browser 的 profile 里，daemon 存活期间一直有效；`agent-browser close --all` 之后可能需要重登。

## 5. 抓列表的稳定写法

```js
[...document.querySelectorAll('table tr')].map(tr =>
  [...tr.querySelectorAll('td')].map(c => c.innerText.replace(/\s+/g,' ').trim())
).filter(td => /^第\s*\d+\s*章/.test(td[0] || ''))
```

比依赖 class 名稳：番茄的 class 是编译生成的（`arco-tabs-header-title`、`serial-input` 之类），表结构反而稳定。

---

## 6. 草稿箱表格（和章节管理表不是同一张）

草稿箱 tab 里页面上会有**两张表**：上半是章节管理表（含审核状态/发布时间），下半才是草稿箱表：

```
表头：名称 | 字数 | 修改时间 | 操作
```

- 抓草稿箱必须按**表头含「修改时间」**定位表格，不能直接取 `document.querySelectorAll('table tr')`（会混进章节管理表的行）
- 进草稿箱前要先点「草稿箱」tab（`.arco-tabs-header-title`），切完等 4-5 秒表格才刷新
- 行内 `<a>` 是**预览**链接：`/main/writer/preview/{bookId}&{chapterId}`（`target=_blank`）
  → 要进编辑页得自己拼：`/main/writer/{bookId}/publish/{chapterId}?enter_from=newdraft`

## 7. 章号 / 标题：受控 input，只能用原生 setter

```html
<!-- 章号：无 placeholder，宽度约 72 -->
<input type="text" class="serial-input byte-input byte-input-size-default" value="148">
<!-- 标题 -->
<input placeholder="请输入标题" class="serial-input serial-editor-input-hint-area byte-input byte-input-size-default">
```

**不要用「点击 + Ctrl+A + insertText」** —— headless 下焦点会丢失，章号框填不进去，
结果存成「第 章 幕末·双邀」这种残废标题（实践中最常见的翻车点）。

正确写法：

```js
const e = /* 目标 input */;
const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
s.call(e, '148');
e.dispatchEvent(new Event('input',  {bubbles: true}));
e.dispatchEvent(new Event('change', {bubbles: true}));
e.value   // 回读，必须等于写入值
```

两框的定位表达式（页面无 id，class 是编译生成的）：

```js
// 章号：serial-input 里宽度 < 160 的那个（标题框约 508）
[...document.querySelectorAll('input.serial-input')]
  .filter(i => { const w = i.getBoundingClientRect().width; return w > 20 && w < 160; })[0]

// 标题
document.querySelector('input[placeholder="请输入标题"]')
```

## 8. 分卷（volume）—— 后台唯一能建卷的地方

### 8.1 三处控件，只有一处能建

| 位置 | 能做什么 |
|---|---|
| 章节管理页 `.serial-select.flat-serial-select` | 卷**筛选**（不改归属），也是新建章节的默认卷来源 |
| 章节管理页「编辑分卷」弹窗 | `.chapter-volume-list-item-normal > span + i.tomato-edit + i.tomato-delete`，**只能改名/删** |
| **章节编辑页 `.publish-header-volume-wrap`** | 弹 `.serial-modal.editor-volume`：选卷改归属 + **新建分卷** |

### 8.2 卷弹窗 DOM（实测）

```
div.serial-modal.editor-volume.byte-modal
├ div.editor-volume-list
│   ├ div.editor-volume-list-item            ← 新建态
│   │   └ div.editor-volume-list-item-edit
│   │       ├ div.editor-volume-list-item-edit-left
│   │       │    文本「第四卷：」                        ← 后台自动编号，别自己写
│   │       │    └ div.common-input-hint.input
│   │       │         └ input[placeholder=请输入分卷名字][maxlength=16]   ← 只输卷名正文
│   │       │         └ div.common-input-hint-sign 「7/20」               ← 计数含前缀
│   │       ├ i.tomato-confirm.green    ← ★ 绿勾：调接口建卷（唯一有效）
│   │       └ i.tomato-cancel.red       ← 红叉：放弃
│   └ div.editor-volume-list-item           ← 常态
│       └ div.editor-volume-list-item-normal.selected
│           ├ span 「第三卷：中层管理」
│           ├ i.tomato-delete.disabled  （当前卷不可删）
│           └ i.tomato-edit
└ div.byte-modal-footer
    └ div.editor-volume-footer
        ├ div.editor-volume-footer-add-volume   「新建分卷」
        └ button 取消 | button 确定             ← 确定在新建态下 disabled
```

### 8.3 建卷四步

1. 点 `.editor-volume-footer-add-volume`
2. 往 `input[placeholder=请输入分卷名字]` 输**卷名正文**（`合伙人`，不要带「第四卷：」）
3. 点 `i.tomato-confirm`（绿勾）→ 会打 `/api/author/volume/add_volume/v0`
4. 点底部「取消」关窗（**不要点「确定」**，那会把当前章节改到这个新卷）

### 8.4 无效做法（都试过，全废）

| 做法 | 结果 |
|---|---|
| 输完整卷名后按 **Enter** | 只在本地态，关窗即丢弃，**不调接口** |
| 点底部「确定」 | 新建态下 `disabled`；语义是「把当前章节归到选中卷」 |
| 看弹窗列表判断成败 | 不可靠：本地态项和已落库项长得一样 |
| **看章节管理页「卷筛选下拉」** | ✅ 唯一可靠，数据来自服务端 |

### 8.5 平台硬限制：不允许两个空卷并存

```
POST /api/author/volume/add_volume/v0
→ {"code":-4054,"data":null,"message":"暂不支持创建多个无章节的分卷"}
```

新建一卷后它是 0 章，此时再建下一卷必被拒。
**要连续建 N 卷，必须每建一卷就先给它挂至少一章**（或按发布节奏，等上一卷有内容后再建下一卷）。

### 8.6 改章节归属

弹窗里点目标卷的 `span` → 点底部「确定」（此时才可点）→ 页头
`.publish-header-volume-name` 的文本会变 → 再点「存草稿」持久化。

## 9. 段落数：平台 p 数 = 本地段数 + 1

ProseMirror 编辑区末尾会保留一个空 `<p>` 占位，所以灌完 95 段读到 **96 个 p** 是正常的：

- **不占字数**（平台字数与本地净字仍逐字一致）
- **不要为了凑数去删**——删掉可能把末段一起吞掉
- 校验用「p ≥ 段数-1」+「净字数差 ≤30」双条件，别用严格相等
