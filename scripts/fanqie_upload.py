#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fanqie_upload.py — 把本地章节批量上传到番茄小说作家后台「草稿箱」

设计原则
  1. 只写草稿，不点发布。发布（含定时发布）留给人工在后台确认，避免误发与风控。
  2. 幂等：上传前读取后台已有章号，已存在的章节默认跳过，不会产生重复章。
  3. 可断点：每章成功后写入 state 文件，中断后重跑自动接着来。
  4. 硬校验：段落数必须与服务端渲染出的 <p> 数量一致，平台字数与本地字数偏差超阈值即停。

依赖
  - Python 3.8+
  - agent-browser（npm i -g agent-browser && agent-browser install）
  - 事先在同一 agent-browser 会话中登录 fanqienovel.com（扫码或短信验证码）

用法
  python scripts/fanqie_upload.py --book-id 1234567890 --from 139 --to 143 \\
      --file ./《书名》发布版.txt --interval 40
  python scripts/fanqie_upload.py --book-id 1234567890 --from 139 --to 180 \\
      --dir ./chapters --interval 60
  python scripts/fanqie_upload.py --book-id 1234567890 --from 139 --to 143 --dry-run
"""
import argparse
import glob
import io
import json
import os
import re
import subprocess
import sys
import time

BOOK_MANAGE = 'https://fanqienovel.com/main/writer/chapter-manage/%s'
HEAD_RE = re.compile(r'^第\s*(\d{1,4})\s*章[ 　:：.、]*(.*)$')
WORD_TOLERANCE = 30          # 平台字数与本地净字的允许偏差（平台口径略有差异）


# ---------------------------------------------------------------- agent-browser

def find_ab():
    """定位 agent-browser 可执行文件。Windows 下 npm 生成的 .cmd 不能被 CreateProcess 直接调用，
    必须找到 packages 里真正的平台二进制。"""
    home = os.path.expanduser('~')
    pats = [
        os.path.join(home, '.workbuddy/binaries/node/versions/*/node_modules/agent-browser/bin/agent-browser-win32-x64.exe'),
        os.path.join(home, '.workbuddy/binaries/node/versions/*/node_modules/agent-browser/bin/agent-browser-linux-x64'),
        os.path.join(home, '.workbuddy/binaries/node/versions/*/node_modules/agent-browser/bin/agent-browser-linux-musl-x64'),
        os.path.join(home, '.workbuddy/binaries/node/versions/*/node_modules/agent-browser/bin/agent-browser-darwin-arm64'),
        os.path.join(home, '.workbuddy/binaries/node/versions/*/node_modules/agent-browser/bin/agent-browser-darwin-x64'),
        '/usr/local/lib/node_modules/agent-browser/bin/agent-browser-linux-x64',
        '/opt/homebrew/lib/node_modules/agent-browser/bin/agent-browser-darwin-arm64',
    ]
    for p in pats:
        hit = sorted(glob.glob(p))
        if hit:
            return hit[-1]
    return 'agent-browser'


AB = find_ab()


def ab(args, stdin=None, timeout=180):
    r = subprocess.run([AB] + args, input=stdin, capture_output=True,
                       text=True, encoding='utf-8', errors='replace', timeout=timeout)
    return (r.stdout or '') + (r.stderr or '')


def ev(js, timeout=180):
    return ab(['eval', '--stdin'], stdin=js, timeout=timeout)


def ev_json(js, timeout=180):
    """agent-browser eval 返回的是「JSON 字符串的 JSON 字面量」，需要解码两次。"""
    out = ev(js, timeout).strip()
    if not out:
        return None
    try:
        v = json.loads(out)
        if isinstance(v, str):
            v = json.loads(v)
        return v
    except Exception:
        return None


def wait_bool(js, timeout=25, step=1.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = ev_json(js)
        if v is True:
            return True
        time.sleep(step)
    return False


# ---------------------------------------------------------------- 章节读取

def clean_lines(text):
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    return [l.strip() for l in text.split('\n')]


def parse_single(path):
    lines = clean_lines(io.open(path, encoding='utf-8').read())
    if not lines:
        return None
    m = HEAD_RE.match(lines[0].lstrip('\ufeff'))
    if not m:
        raise ValueError('首行不是「第N章 标题」格式：%s → %r' % (os.path.basename(path), lines[0][:40]))
    body = [l for l in lines[1:] if l]
    return {'num': int(m.group(1)), 'name': m.group(2).strip() or '未命名', 'body': body}


def parse_merged(path):
    """从一个合并 txt 里按「第N章 标题」切出所有章节。"""
    txt = io.open(path, encoding='utf-8').read().replace('\r\n', '\n').replace('\r', '\n')
    lines = txt.split('\n')
    out, cur = [], None
    for ln in lines:
        m = HEAD_RE.match(ln.strip())
        if m:
            if cur:
                out.append(cur)
            cur = {'num': int(m.group(1)), 'name': m.group(2).strip() or '未命名', 'lines': []}
        elif cur is not None and ln.strip():
            cur['lines'].append(ln.strip())
    if cur:
        out.append(cur)
    for c in out:
        c['body'] = c.pop('lines')
    return out


def load_chapters(args):
    chapters = {}
    if args.file:
        for c in parse_merged(args.file):
            chapters[c['num']] = c
    if args.dir:
        files = sorted(glob.glob(os.path.join(args.dir, '*.txt')))
        if not files:
            raise SystemExit('目录里没有 .txt：%s' % args.dir)
        for f in files:
            c = parse_single(f)
            if c:
                chapters[c['num']] = c
    if not chapters:
        raise SystemExit('没有读到任何章节，检查 --file / --dir')
    picked = [chapters[n] for n in sorted(chapters) if args.a <= n <= args.b]
    if not picked:
        raise SystemExit('第 %d-%d 章区间内没有章节' % (args.a, args.b))
    return picked


# ---------------------------------------------------------------- 后台交互

JS_HAS = {
    'manage': """!!([...document.querySelectorAll('[role="tab"]')].find(t=>t.innerText.includes('草稿箱')))""",
    'newdraft': """!!([...document.querySelectorAll('button')].find(b=>b.innerText.includes('新建草稿')))""",
    'editor': """document.querySelectorAll('.ProseMirror').length > 0""",
    'title': """!!document.querySelector('input[placeholder="请输入标题"]')""",
}


def click_button(text, exact=False):
    js = ("""(() => {const b=[...document.querySelectorAll('button')].find(x=>%s);
             if(!b) return 'x'; b.click(); return 'ok';})()"""
          % ('x.innerText.trim()===%s' % json.dumps(text, ensure_ascii=False) if exact
             else 'x.innerText.includes(%s)' % json.dumps(text, ensure_ascii=False)))
    return 'ok' in ev(js)


def read_existing_nums(book_id):
    """读取后台已有章号（已发布 + 待发布 + 草稿箱），用于幂等跳过。"""
    nums = set()
    ab(['open', BOOK_MANAGE % book_id], timeout=120)
    if not wait_bool(JS_HAS['manage'], timeout=40):
        return None
    for tab in ('章节管理', '草稿箱'):
        ev("""(() => {const t=[...document.querySelectorAll('[role="tab"]')].find(x=>x.innerText.includes(%s));
                if(t) t.click(); return 'ok';})()""" % json.dumps(tab, ensure_ascii=False))
        time.sleep(2.0)
        rows = ev_json("""(() => {const r=[...document.querySelectorAll('a')].map(a=>a.innerText.trim())
                    .filter(t=>/^第\\s*\\d+\\s*章/.test(t));
                    return JSON.stringify(r);})()""") or []
        for t in rows:
            m = HEAD_RE.match(t) or re.match(r'^第\s*(\d+)\s*章', t)
            if m:
                nums.add(int(m.group(1)))
    return nums


def upload_one(book_id, ch, interval_note=''):
    n, name = ch['num'], ch['name']
    ab(['open', BOOK_MANAGE % book_id], timeout=120)
    if not wait_bool(JS_HAS['manage'], timeout=40):
        return False, '章节管理页未就绪（大概率掉登录了，重新扫码/验证码登录后重跑）'

    ev("""(() => {const t=[...document.querySelectorAll('[role="tab"]')].find(x=>x.innerText.includes('草稿箱'));
            if(!t) return 'x'; t.click(); return 'ok';})()""")
    if not wait_bool(JS_HAS['newdraft'], timeout=25):
        return False, '草稿箱 tab 未出现「新建草稿」按钮'

    if not click_button('新建草稿'):
        return False, '点击「新建草稿」失败'
    if not wait_bool("""location.href.includes('/publish/')""", timeout=30):
        return False, '未进入编辑页'
    if not wait_bool(JS_HAS['editor'], timeout=30):
        return False, '编辑页 ProseMirror 未渲染'
    if not wait_bool(JS_HAS['title'], timeout=15):
        return False, '编辑页标题框未渲染'
    time.sleep(0.6)

    ab(['type', 'input.byte-input', str(n)])
    ab(['type', 'input[placeholder="请输入标题"]', name])

    js = ("(() => {\n  const paras = " + json.dumps(ch['body'], ensure_ascii=False) + ";\n"
          "  const el = document.querySelectorAll('.ProseMirror')[0];\n"
          "  if (!el) return JSON.stringify({err:'no editor'});\n"
          "  el.focus();\n"
          "  document.execCommand('selectAll');\n"
          "  document.execCommand('delete');\n"
          "  const ok = document.execCommand('insertText', false, paras.join('\\n'));\n"
          "  return JSON.stringify({ok, ps: el.querySelectorAll('p').length});\n})()\n")
    st = ev_json(js, timeout=180)
    if not st or not st.get('ok'):
        return False, '正文写入失败：%s' % st
    if st['ps'] != len(ch['body']):
        return False, '段落数不符：编辑器 %s / 源 %s' % (st['ps'], len(ch['body']))

    if click_button('继续编辑本地'):
        time.sleep(1.2)   # 版本冲突弹窗，保留本地内容

    if not click_button('存草稿', exact=True):
        return False, '找不到「存草稿」按钮'
    if not wait_bool("""document.body.innerText.includes('已保存')""", timeout=20):
        return False, '保存后未见「已保存」回执'

    got = ev_json("""(() => {const r=document.body.innerText.match(/正文字数[\\s\\n]*(\\d+)/);
                      return JSON.stringify({w: r ? parseInt(r[1]) : -1});})()""")
    w = got.get('w', -1) if isinstance(got, dict) else -1
    if w > 0 and abs(w - len(''.join(ch['body']))) > WORD_TOLERANCE * max(1, len(ch['body']) // 100):
        return False, '字数偏差过大：平台 %s / 源 %s' % (w, len(''.join(ch['body'])))
    return True, 'ok (平台字数 %s)' % w


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description='番茄作家后台批量上传草稿')
    ap.add_argument('--book-id', required=True, help='作家后台 URL 里的作品 ID')
    ap.add_argument('--from', dest='a', type=int, required=True)
    ap.add_argument('--to', dest='b', type=int, required=True)
    ap.add_argument('--file', help='合并的发布版 txt（按「第N章 标题」自动切章）')
    ap.add_argument('--dir', help='单章 txt 目录（首行须为「第N章 标题」）')
    ap.add_argument('--interval', type=int, default=45, help='每章间隔秒数，默认 45')
    ap.add_argument('--state', default='.fanqie_upload_state.json', help='断点记录文件')
    ap.add_argument('--dry-run', action='store_true', help='只解析不写入')
    ap.add_argument('--force', action='store_true', help='不检查后台已有章，强制上传')
    a = ap.parse_args()

    if not a.file and not a.dir:
        sys.exit('必须指定 --file 或 --dir')

    chapters = load_chapters(a)
    print('解析到 %d 章：第%d-%d章' % (len(chapters), chapters[0]['num'], chapters[-1]['num']))

    state = {}
    if os.path.exists(a.state):
        try:
            state = json.load(io.open(a.state, encoding='utf-8'))
        except Exception:
            state = {}
    done = set(state.get('done', []))

    existing = set()
    if not a.force and not a.dry_run:
        print('读取后台已有章号…')
        got = read_existing_nums(a.book_id)
        if got is None:
            sys.exit('无法读取后台，请确认已登录 fanqienovel.com')
        existing = got
        print('后台已有 %d 章（最大第%d章）' % (len(existing), max(existing) if existing else 0))

    ok_n, skip_n, fail = 0, 0, 0
    for i, ch in enumerate(chapters):
        n = ch['num']
        tag = '第%d章《%s》 %d 段 / %d 字' % (n, ch['name'], len(ch['body']), sum(len(x) for x in ch['body']))
        if n in done and not a.force:
            print('· 跳过（本地已记录）%s' % tag)
            skip_n += 1
            continue
        if n in existing and not a.force:
            print('· 跳过（后台已存在）%s' % tag)
            skip_n += 1
            continue
        print('→ %s' % tag)
        if a.dry_run:
            continue
        ok, msg = upload_one(a.book_id, ch)
        if not ok:
            print('   [FAIL] %s' % msg)
            fail += 1
            print('   已停止。修复后从 --from %d 重跑即可（已完成的会自动跳过）' % n)
            break
        print('   [OK] %s' % msg)
        done.add(n)
        state['done'] = sorted(done)
        state['book_id'] = a.book_id
        io.open(a.state, 'w', encoding='utf-8').write(json.dumps(state, ensure_ascii=False, indent=1))
        ok_n += 1
        if i < len(chapters) - 1:
            time.sleep(a.interval)

    print('\n完成：新增 %d，跳过 %d，失败 %d' % (ok_n, skip_n, fail))
    if fail:
        sys.exit(1)


if __name__ == '__main__':
    main()
