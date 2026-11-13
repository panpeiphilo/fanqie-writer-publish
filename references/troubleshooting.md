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

---

## 8. `agent-browser open` 恒报 `Chrome exited early (exit code 0)`

**症状**：`doctor` 的 launch test 直接 fail；`eval` / `connect` 有时不是失败而是被
**SIGTERM 打断**（进程直接没输出就死）。

**原因**：agent-browser 内部自起 Chrome 的通道在部分 Windows/RDP 环境不可用，
与 Node、与 Chrome 版本都无关，换 profile 也没用。

**处理**：**弃用 agent-browser，改纯 CDP 通道**：

```bash
python scripts/fanqie_upload_cdp.py --book-id <bookId> --from 148 --to 149 --dir ./chapters
python scripts/fanqie_volume.py --book-id <bookId> --list
```

`scripts/cdp_client.py` 自带零依赖 CDP 客户端（手写 WebSocket），
用 `--headless=new` 起 Chrome + 持久 profile，可以复用已登录的 cookie。

## 9. 建卷报 `-4054 暂不支持创建多个无章节的分卷`

**不是脚本 bug，是平台规则**：后台不允许同时存在两个空卷。

**处理**：先给已建好的空卷挂上至少一章（上传一章到该卷），再建下一卷；
或者干脆按发布节奏走——上一卷快要启用时再建下一卷。

## 10. 草稿存成「第 章 XXX」（章号丢失）

**原因**：用「点击 + Ctrl+A + insertText」填章号框，headless 下焦点丢失，
只有标题填进去了。

**处理**：
1. 改用原生 setter（见 `backend-dom.md` §7）；
2. 写完必须回读 `input.value` 比对；
3. 已经存坏的，用编辑页 URL 打开该草稿补章号：行内 `<a href>` 里带 `chapterId`，
   拼 `/publish/{chapterId}?enter_from=newdraft` 即可直达，不用点列表。

## 11. 正文只进去 2 段 / 存成空章

**原因**：`document.execCommand('insertText')` 需要编辑器**真实焦点**，
直接 `el.focus()` 在 headless 下不够。

**处理**：先用 `Input.dispatchMouseEvent` 在编辑器区域内点一下，再 `focus()` +
`selectAll` + `delete` + `insertText`，然后按 `<p>` 数量与净字数双校验，
不符重试（最多 3 次）。`fanqie_upload_cdp.py` 的 `inject_body()` 已内置。

## 12. `Page.close` 之后所有命令 30s 超时

**原因**：关掉的正是自己连着的那个标签页，WebSocket 随之失效。

**处理**：**不要对主标签页调 `Page.close`**。要换页面就 `Page.navigate` 到新 URL。

## 13. `TimeoutError: timed out`（`Page.navigate` 无响应）

**原因**：socket 超时太短（默认 30s），章节管理页首次加载会超过。

**处理**：`cdp_client.WS(timeout=120)`、`CDP.call` 循环 180s（已在脚本里设好）。
另外 Chrome 起不来时 `launch()` 会自动重试 3 次——「启动即退出 exit=0」是偶发的。

## 14. 幂等判定要看卷，不能只看章号

只按章号跳过的话，「章号对但卷错」的章节会被静默放过、永远修不好。

**处理**：跳过条件写 `章号已存在`；若还需校验归属，用
`fanqie_volume.py --assign 148="第三卷：中层管理"` 显式改，别指望自动修。

## 15. `--list` 卷列表是空的 / 一开跑就跳登录页

**症状**：脚本能起 Chrome，也不报错，但「服务端卷列表」一条都没有；
或者 `location.href` 里带 `/login`。

**原因**：Chrome 用的 profile 不是你登录过的那个。登录态（Cookies）是按
`--user-data-dir` 隔离的，换了目录就等于换了个没登录的浏览器。
典型场景：默认在 `~/.fanqie-profile`，而你当初是在书稿目录旁边
（比如 `D:/Data/WorkBuddy/.fanqie-profile`）扫的码。

**排查**（一条命令看清最终用的是哪个目录、从哪来的）：

```bash
python scripts/fanqie_config.py
```

```
profile   : D:/Data/WorkBuddy/.fanqie-profile        [config.json]
✅ profile 可用：D:/Data/WorkBuddy/.fanqie-profile
```

- 来源列显示 `[config.json]` / `[环境变量 FANQIE_PROFILE]` / `[自动发现（含登录态）]` / `[默认]`
- 打 ❌ 说明目录都不存在；打 ⚠️ 说明目录在但没有 Cookies（没登录过或登录态已过期）

**处理**（三选一，优先级从高到低）：

```bash
# 1) 写进配置文件（一劳永逸）
cp config.example.json config.json
#    改 config.json 里的 "profile" 为真正有登录态的那个目录

# 2) 环境变量（临时）
FANQIE_PROFILE="D:/Data/WorkBuddy/.fanqie-profile" python scripts/fanqie_volume.py --list

# 3) 重新登录到这个 profile
python scripts/fanqie_upload_cdp.py --from 1 --to 1 --dir ./ch --headed
```

**自动发现**：没有配置、且默认目录为空时，脚本会依次在
`<当前目录>/.fanqie-profile`、`<上级目录>/.fanqie-profile`、`~/.fanqie-profile`、
`<skill根>/.fanqie-profile` 里找一个带 Cookies 的用，并在自检里标成
`[自动发现（含登录态）]`。所以「登录态在书稿目录旁边」这种情况通常直接能跑，
但**换个目录执行就可能失效**——长期用还是显式写进 `config.json` 稳妥。

> 判断「有没有登录态」的口径：profile 目录下存在
> `Default/Network/Cookies`（新版 Chrome）或 `Default/Cookies`（旧版）。
