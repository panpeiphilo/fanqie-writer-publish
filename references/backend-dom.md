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
