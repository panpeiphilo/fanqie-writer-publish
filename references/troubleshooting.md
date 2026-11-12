# 故障排查

按症状索引。

## 1. `FileNotFoundError: [WinError 2]` 或 `agent-browser: command not found`

**原因**：Windows 下 npm 生成的 `agent-browser.cmd` 是批处理包装，`subprocess` 用 `CreateProcess` 无法直接执行它（macOS/Linux 的 shim 同理）。

**处理**：定位真正的平台二进制。`agent-browser.cmd` 内容会告诉你路径：

```bat
@ECHO OFF
"%~dp0node_modules\agent-browser\bin\agent-browser-win32-x64.exe" %*
```

脚本里的 `find_ab()` 已按 glob 自动找：

```
~/.workbuddy/binaries/node/versions/*/node_modules/agent-browser/bin/agent-browser-<platform>
/usr/local/lib/node_modules/agent-browser/bin/agent-browser-linux-x64
```

找不到就 `npm root -g` 查一下实际位置，把路径加进 `find_ab()` 的候选列表。

## 2. `agent-browser --version` 正常但一跑就崩

**原因**：PATH 上的 `node` 是坏的（SIGILL / exit 133）。agent-browser 内部会 spawn 一个 Node 子进程。

**验证**：

```bash
node -e "console.log('ok')"
```

不输出 `ok` 就是 Node 的问题。换一个可用 Node，或在命令前临时前置 PATH。

## 3. 扫码登录二维码扫不出来

按顺序排查：

| 现象 | 原因 | 处理 |
|---|---|---|
| 截图里的码很小、糊 | 整页截图，二维码只占 148px | 从页面直接取原图：`img[src^="data:image/png;base64"]`，原图 512×512 |
| 取出来还是扫不了 | 超过 2 分钟有效期 | 重新加载页面刷新二维码，立刻扫 |
| 放大到 5 倍仍然不行 | 远程桌面（RDP）画面压缩，细密模块糊了 | 改走「验证码登录」：输手机号 → 点获取验证码 → 人工报 6 位码 |
| 提示「二维码已失效」 | 页面停留太久 | 同第 2 条 |

取原图的命令：

```bash
agent-browser eval "document.querySelector('img[src^=\"data:image/png;base64\"]').src"
```

## 4. 「章节管理页未就绪（掉登录）」

- 先确认没有被踢下线：`agent-browser eval "location.href"`，如果跳到 `/main/writer/login` 就是掉登录了。
- `agent-browser close --all` 之后 profile 可能换新，需要重登。
- 也可能是页面还没渲染完：把 `wait_bool` 的 timeout 从 40 调到 60 再试。

## 5. 「草稿箱 tab 未出现新建草稿」

必须**先点草稿箱 tab**。停在「章节管理」tab 时，页面上只有「新建章节」。检查 tab 选择的 JS 是否真的点到了（`[role="tab"]` 的 innerText 是否包含「草稿箱」）。

## 6. 「编辑页 ProseMirror 未渲染」

SPA 从路由跳转后编辑器挂载有延迟，实测 2-5 秒。脚本已等 30 秒；仍失败说明页面白屏或接口 500，重新 `open` 一次。

## 7. 保存了但正文是空的

**几乎一定是用了 `innerHTML` 注入**。ProseMirror 不认 DOM 直接改写，必须走 `execCommand('insertText')` 或模拟键盘输入。用 `el.querySelectorAll('p').length` 自检能立刻发现。

## 8. 「段落数不符」

| 可能原因 | 检查 |
|---|---|
| 源 txt 里有全角空格（`　`）或零宽字符 | 清洗后再注入 |
| 段落中有空段 | 解析时已过滤空行，若 PM 仍多出段落，说明某个字符触发 splitBlock |
| 编辑器里残留旧内容 | 注入前必须 `selectAll` + `delete` |

排除法：先只注入前 5 段，看 `p` 数，再全量。

## 9. 「字数偏差过大」

- 差 1-3 字：正常，平台标点口径不同。
- 差几十字：可能有段落被吞（检查开头和结尾），或源文件本身截断。
- 平台显示 `-`：刚提交/审核中的章节列表可能不显示字数，去 `preview` 页面看实际内容。

## 10. 版本冲突弹窗反复出现

**原因**：同一个草稿在多端同时打开。自动化跑之前把内置浏览器里同作品的编辑页关掉。

脚本处理是点「继续编辑本地」，但更根本的办法是避免并发编辑。

## 11. 章号重复了怎么办

后台不会拦截重复章号。发现重复后：

1. 在章节管理页找到重复的那一章
2. 删除（部分状态下删除需要走审核/客服）
3. 用 `--force` 重传前，先确认 `read_existing_nums` 是否正常工作

预防：默认开启「后台已有章号跳过」，不要随手加 `--force`。

## 12. 抓不到章节行

列表可能是虚拟滚动，或表结构改版。用 `agent-browser snapshot` 看真实结构，然后改 `check_status.py` 里的 `GRAB` 选择器。class 名不可靠（编译生成），优先依赖 `table tr` + `td` 顺序。
