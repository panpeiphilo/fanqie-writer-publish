#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cdp_client.py — 零依赖 CDP 客户端（只用标准库）

为什么自带这套：agent-browser 在部分机器上会失败（`Chrome exited early`、
`eval/connect` 被 SIGTERM 打断），而 Chrome 自己开的 DevTools 端口永远可用。
本模块只做三件事：起 Chrome（带持久 profile，登录态可复用）、连上某个标签页、
在页面里执行 JS / 派发真实鼠标键盘事件。

设计约束
  - 只在脚本运行期间持有 Chrome；脚本退出 Chrome 随之结束
  - **一次进程内干完全部动作**：跨脚本调用无法保持浏览器会话
  - profile 默认放在用户目录下的 .fanqie-profile，登录一次长期复用
"""
import base64
import json
import os
import socket
import struct
import subprocess
import sys
import time
import urllib.request

PORT = int(os.environ.get('FANQIE_CDP_PORT', '9333'))
PROFILE = os.environ.get('FANQIE_PROFILE') or os.path.join(
    os.path.expanduser('~'), '.fanqie-profile')

CHROME_CANDS = [
    os.environ.get('CHROME_PATH') or '',
    r'C:\Program Files\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
]


def find_chrome():
    for p in CHROME_CANDS:
        if p and os.path.exists(p):
            return p
    raise SystemExit('找不到 Chrome。可用环境变量 CHROME_PATH 指定可执行文件路径')


# ------------------------------------------------------------------ WebSocket

class WS:
    """最小 WebSocket 客户端：文本帧 + 分片 + ping/pong，够 CDP 用。"""

    def __init__(self, url, timeout=120):
        assert url.startswith('ws://'), url
        rest = url[5:]
        hostport, path = rest.split('/', 1)
        path = '/' + path
        host, port = hostport.split(':')
        self.sock = socket.create_connection((host, int(port)), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = ('GET %s HTTP/1.1\r\nHost: %s:%s\r\nUpgrade: websocket\r\n'
               'Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n'
               'Sec-WebSocket-Version: 13\r\n\r\n' % (path, host, port, key))
        self.sock.sendall(req.encode())
        buf = b''
        while b'\r\n\r\n' not in buf:
            buf += self.sock.recv(4096)
        head, self.buf = buf.split(b'\r\n\r\n', 1)
        if b'101' not in head.split(b'\r\n')[0]:
            raise RuntimeError('WS 握手失败: %r' % head[:200])
        self.frag = b''

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError('socket closed')
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send(self, text):
        data = text.encode('utf-8')
        mask = os.urandom(4)
        ln = len(data)
        if ln < 126:
            hdr = struct.pack('!BB', 0x81, 0x80 | ln)
        elif ln < 65536:
            hdr = struct.pack('!BBH', 0x81, 0x80 | 126, ln)
        else:
            hdr = struct.pack('!BBQ', 0x81, 0x80 | 127, ln)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self.sock.sendall(hdr + mask + masked)

    def recv(self):
        while True:
            b1, b2 = self._read(2)
            opcode = b1 & 0x0F
            ln = b2 & 0x7F
            if ln == 126:
                ln = struct.unpack('!H', self._read(2))[0]
            elif ln == 127:
                ln = struct.unpack('!Q', self._read(8))[0]
            payload = self._read(ln) if ln else b''
            if opcode == 0x9:                       # ping → pong
                mask = os.urandom(4)
                m = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
                self.sock.sendall(struct.pack('!BB', 0x8A, 0x80 | len(payload)) + mask + m)
                continue
            if opcode == 0x8:
                raise RuntimeError('WS closed by peer')
            if opcode == 0x1:
                self.frag = payload
                return payload.decode('utf-8', 'replace')
            if opcode == 0x0:
                self.frag += payload
                return self.frag.decode('utf-8', 'replace')

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


# ------------------------------------------------------------------ CDP

class CDP:
    def __init__(self, ws_url):
        self.ws = WS(ws_url)
        self.n = 0

    def call(self, method, **params):
        self.n += 1
        mid = self.n
        self.ws.send(json.dumps({'id': mid, 'method': method, 'params': params}))
        t0 = time.time()
        while time.time() - t0 < 180:
            msg = json.loads(self.ws.recv())
            if msg.get('id') == mid:
                if 'error' in msg:
                    raise RuntimeError('%s → %s' % (method, msg['error']))
                return msg.get('result', {})
        raise RuntimeError('%s 超时' % method)

    def js(self, expr, await_promise=False):
        r = self.call('Runtime.evaluate', expression=expr, returnByValue=True,
                      awaitPromise=await_promise)
        return r.get('result', {}).get('value')

    def goto(self, url, settle=3.0, wait_js=None, timeout=60):
        self.call('Page.navigate', url=url)
        t0 = time.time()
        while time.time() - t0 < timeout:
            time.sleep(1.0)
            try:
                ready = self.js('document.readyState')
            except Exception:
                ready = None
            if ready == 'complete':
                if not wait_js:
                    break
                try:
                    if self.js(wait_js) is True:
                        break
                except Exception:
                    pass
        time.sleep(settle)

    # -- 真实输入事件（React 只认这些，element.click() 无效）

    def click_at(self, x, y):
        self.call('Input.dispatchMouseEvent', type='mouseMoved', x=x, y=y)
        time.sleep(0.12)
        self.call('Input.dispatchMouseEvent', type='mousePressed', x=x, y=y,
                  button='left', clickCount=1)
        time.sleep(0.09)
        self.call('Input.dispatchMouseEvent', type='mouseReleased', x=x, y=y,
                  button='left', clickCount=1)

    def insert_text(self, text):
        self.call('Input.insertText', text=text)


# ------------------------------------------------------------------ Chrome 进程

def port_alive(port=PORT):
    try:
        urllib.request.urlopen('http://127.0.0.1:%d/json/version' % port, timeout=1.5).read()
        return True
    except Exception:
        return False


def launch(headless=True, tries=3, port=PORT, profile=None):
    """起 Chrome 并等调试端口就绪。已有实例占用端口则直接复用。

    Chrome 偶发「启动即退出 exit=0」，所以内置重试。
    """
    if port_alive(port):
        return None
    profile = profile or PROFILE
    os.makedirs(profile, exist_ok=True)
    args = [find_chrome(), '--remote-debugging-port=%d' % port,
            '--remote-allow-origins=*', '--user-data-dir=%s' % profile,
            '--no-first-run', '--no-default-browser-check',
            '--disable-features=Translate,OptimizationHints',
            '--window-size=1440,1000']
    if headless:
        args += ['--headless=new', '--disable-gpu', '--hide-scrollbars']
    args.append('about:blank')

    last = None
    for _ in range(tries):
        p = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             stdin=subprocess.DEVNULL)
        for _ in range(60):
            time.sleep(0.5)
            if port_alive(port):
                return p
            if p.poll() is not None:
                last = 'exit=%s' % p.returncode
                break
        time.sleep(2)
    raise SystemExit('Chrome 调试端口未就绪（%s）' % (last or 'timeout'))


def list_pages(port=PORT):
    d = json.load(urllib.request.urlopen('http://127.0.0.1:%d/json/list' % port, timeout=3))
    return [t for t in d if t.get('type') == 'page' and t.get('webSocketDebuggerUrl')]


def connect(port=PORT, want=None, timeout=30):
    """连到某个标签页。want 为 URL 片段，命中即返回；否则取第一个 page。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        pages = list_pages(port)
        if want:
            for t in pages:
                if want in t.get('url', ''):
                    return _open(t)
        if pages:
            return _open(pages[0])
        time.sleep(1.0)
    raise SystemExit('没有可用的标签页')


def _open(target):
    c = CDP(target['webSocketDebuggerUrl'])
    c.call('Runtime.enable')
    c.call('Page.enable')
    return c


def close_browser(cdp=None):
    """干净退出，cookie 才会落盘"""
    if cdp is not None:
        try:
            cdp.call('Browser.close')
            return
        except Exception:
            pass
    try:
        urllib.request.urlopen('http://127.0.0.1:%d/json/close' % PORT, timeout=2)
    except Exception:
        pass


if __name__ == '__main__':
    # 自检：起 Chrome → 打开空白页 → 读 UA → 关闭
    launch(headless=True)
    c = connect()
    print('url:', c.js('location.href'))
    print('ua :', c.js('navigator.userAgent'))
    close_browser(c)
    print('ok')
