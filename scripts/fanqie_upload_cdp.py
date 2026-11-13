#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fanqie_upload_cdp.py — 纯 CDP 通道：把本地章节灌进番茄作家后台草稿箱

和 fanqie_upload.py 的区别：不依赖 agent-browser（那套在本机会起不来），
自己起 Chrome、自己说 CDP，所以在任何装了 Chrome 的机器上都能跑。

用法
  # 单章 txt 目录
  python scripts/fanqie_upload_cdp.py --book-id 7682830798759676952 \
      --from 148 --to 149 --dir "D:/book/03-发布版" --volume "第三卷：中层管理"

  # 合并成一个 txt 的发布版
  python scripts/fanqie_upload_cdp.py --book-id 7682830798759676952 \
      --from 148 --to 149 --file "./《书名》发布版.txt"

  # 只看解析，不写后台
  python scripts/fanqie_upload_cdp.py --book-id X --from 148 --to 149 --dir ./ch --dry-run

设计
  - 只点「存草稿」，永不点「下一步」
  - 幂等：先读草稿箱已有章号，已存在的跳过
  - 每章存完回读草稿箱确认，未见本章即停（不静默跳过）
  - 动作全部在同一个进程内完成：Chrome 随脚本退出而结束，不能跨调用保持会话
"""
import argparse
import glob
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdp_client as C  # noqa: E402
import fanqie_config as CFG  # noqa: E402

MANAGE = 'https://fanqienovel.com/main/writer/chapter-manage/%s'
HEAD_RE = re.compile(r'^第\s*(\d{1,4})\s*章[\s　:：.、]*(.*)$')
WORD_TOLERANCE = 30

# 章号框：class 含 serial-input 且宽度 < 160（标题框约 508）
NUM_EXPR = ("[...document.querySelectorAll('input.serial-input')]"
            ".filter(i=>{const w=i.getBoundingClientRect().width;return w>20&&w<160;})[0]")
TITLE_EXPR = "document.querySelector('input[placeholder=\"请输入标题\"]')"


# ---------------------------------------------------------------- 章节解析

def parse_file(path, lo, hi):
    """合并版 txt：按「第N章 标题」切章"""
    raw = open(path, encoding='utf-8').read().replace('\r\n', '\n')
    out, cur = [], None
    for line in raw.split('\n'):
        m = HEAD_RE.match(line.strip())
        if m:
            if cur:
                out.append(cur)
            cur = {'num': int(m.group(1)), 'title': m.group(2).strip(), 'paras': []}
            continue
        if cur is not None and line.strip():
            cur['paras'].append(line.strip())
    if cur:
        out.append(cur)
    return [c for c in out if lo <= c['num'] <= hi and c['paras']]


def parse_dir(path, lo, hi):
    out = []
    for f in sorted(glob.glob(os.path.join(path, '*.txt'))):
        base = os.path.basename(f)
        m = re.match(r'^第\s*(\d{1,4})\s*章[_\-\s]*(.*)\.txt$', base)
        if not m:
            continue
        num = int(m.group(1))
        if not (lo <= num <= hi):
            continue
        raw = open(f, encoding='utf-8').read().replace('\r\n', '\n')
        lines = [l.rstrip() for l in raw.split('\n')]
        head = HEAD_RE.match(lines[0].strip()) if lines else None
        title = head.group(2).strip() if head else m.group(2).strip()
        paras = [l.strip() for l in lines[1:] if l.strip()]
        out.append({'num': num, 'title': title, 'paras': paras, 'file': f})
    return out


# ---------------------------------------------------------------- 页面操作

def manage_home(cdp, book_id):
    """打开章节管理页并切到草稿箱 tab"""
    cdp.goto(MANAGE % book_id, settle=4.0,
             wait_js="!!document.querySelector('table')", timeout=90)
    for _ in range(2):
        if not click_text(cdp, '我知道了', 'button,div,span,a'):
            break
        time.sleep(1.0)
    click_text(cdp, '草稿箱', 'div')
    time.sleep(5.0)


def click_at_js(cdp, expr):
    b = cdp.js("""(() => {const e=%s; if(!e) return '';
        const r=e.getBoundingClientRect();
        if(r.width<3||r.height<3) return '';
        return JSON.stringify({x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)});})()"""
               % expr)
    if not b:
        return False
    p = json.loads(b)
    cdp.click_at(p['x'], p['y'])
    return True


def click_text(cdp, text, tags='button,div,span,a'):
    b = cdp.js("""(() => {
      const want=%s; const out=[];
      for (const e of document.querySelectorAll(%s)) {
        if (e.children.length>1) continue;
        const t=(e.innerText||e.textContent||'').trim();
        if (t!==want) continue;
        const r=e.getBoundingClientRect();
        if (r.width<4||r.height<4) continue;
        out.push({x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2),w:Math.round(r.width)});
      }
      out.sort((a,b)=>a.w-b.w);
      return JSON.stringify(out.slice(0,3));
    })()""" % (json.dumps(text), tags))
    hits = json.loads(b or '[]')
    if not hits:
        return False
    cdp.click_at(hits[0]['x'], hits[0]['y'])
    return True


def draft_list(cdp):
    """草稿箱表格（表头含「修改时间」）→ [[名称, 字数], ...]"""
    b = cdp.js(r"""(() => {
      const out=[];
      for (const tb of document.querySelectorAll('table')) {
        const ths=[...tb.querySelectorAll('th')].map(th=>(th.innerText||'').trim());
        if (!ths.some(t=>t.indexOf('修改时间')>=0)) continue;
        for (const tr of tb.querySelectorAll('tbody tr, tr')) {
          const tds=[...tr.querySelectorAll('td')].map(td=>(td.innerText||'').replace(/\s+/g,' ').trim());
          if (tds.length>=2 && tds[0]) out.push([tds[0], tds[1]]);
        }
      }
      return JSON.stringify(out);
    })()""")
    return json.loads(b or '[]')


def open_new_draft(cdp):
    """草稿箱 → 新建草稿 → 返回编辑页（同标签页内跳转）"""
    if not click_text(cdp, '新建草稿', 'button,div,span,a'):
        return '未找到「新建草稿」按钮（是否停在章节管理 tab？）'
    ok = wait_js(cdp, "!!document.querySelector('.ProseMirror')", 45)
    if not ok:
        return '新建草稿后编辑器未渲染'
    time.sleep(1.5)
    return None


def wait_js(cdp, expr, timeout=40, step=0.5):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if cdp.js(expr) is True:
                return True
        except Exception:
            pass
        time.sleep(step)
    return False


def set_input(cdp, expr, value):
    """React 受控 input：原生 setter + input/change 事件。
    不要用「点击 + Ctrl+A + insertText」——headless 下焦点会丢，章号框会填不进去。"""
    return cdp.js("""(() => {
      const e=%s;
      if(!e) return 'no-el';
      const s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
      s.call(e, %s);
      e.dispatchEvent(new Event('input',{bubbles:true}));
      e.dispatchEvent(new Event('change',{bubbles:true}));
      return e.value;
    })()""" % (expr, json.dumps(str(value))))


def inject_body(cdp, paras, retries=3):
    """正文是 ProseMirror：必须先真实点击编辑器拿到焦点，再用 execCommand。
    插入后按 <p> 数量与净字数双校验，不符重试。"""
    text = '\n'.join(paras)
    want = len(paras)
    want_chars = len(text.replace('\n', ''))
    n = 0
    for _ in range(retries):
        if not click_at_js(cdp, "document.querySelectorAll('.ProseMirror')[0]"):
            time.sleep(1.5)
            continue
        time.sleep(0.4)
        cdp.js("""(() => {
          const el=document.querySelectorAll('.ProseMirror')[0];
          el.focus();
          document.execCommand('selectAll');
          document.execCommand('delete');
          return 1;
        })()""")
        time.sleep(0.5)
        cdp.insert_text(text)
        time.sleep(2.5)
        st = json.loads(cdp.js(r"""(() => {
          const el=document.querySelectorAll('.ProseMirror')[0];
          return JSON.stringify({p: el?el.querySelectorAll('p').length:0,
            chars: el?(el.innerText||'').replace(/\s+/g,'').length:0});
        })()""") or '{}')
        n = st.get('p', 0)
        # 平台常见 p 数 = 段数 + 1（末尾占位空段），所以用「≥ 段数-1」+ 字数双重判定
        if n >= want - 1 and abs(st.get('chars', 0) - want_chars) <= WORD_TOLERANCE:
            return {'p': n, 'chars': st.get('chars'), 'ok': True}
        time.sleep(1.5)
    return {'p': n, 'ok': False}


def set_volume(cdp, vol):
    """把本章归到指定分卷。卷控件在编辑页顶部。"""
    if not vol:
        return 'skipped'
    cur = cdp.js("""(() => {const e=document.querySelector('.publish-header-volume-name');
        return e?e.innerText.trim():'';})()""")
    if cur == vol:
        return 'already'
    if not click_at_js(cdp, "document.querySelector('.publish-header-volume-wrap')"):
        return 'no-widget'
    time.sleep(1.8)
    hit = cdp.js("""(() => {
      const want=%s; const root=document.querySelector('.serial-modal.editor-volume');
      if(!root) return '';
      for (const it of root.querySelectorAll('.editor-volume-list-item-normal')) {
        const s=it.querySelector('span');
        if (s && s.innerText.trim()===want) {
          const r=s.getBoundingClientRect();
          return JSON.stringify({x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)});
        }
      }
      return '';
    })()""" % json.dumps(vol))
    if not hit:
        click_text(cdp, '取消')
        return 'volume-not-found'
    p = json.loads(hit)
    cdp.click_at(p['x'], p['y'])
    time.sleep(0.8)
    ok = cdp.js("""(() => {const b=[...document.querySelectorAll('.serial-modal.editor-volume button')]
        .find(x=>(x.innerText||'').trim()==='确定');
        if(!b||b.disabled) return '';
        const r=b.getBoundingClientRect();
        return JSON.stringify({x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)});})()""")
    if not ok:
        click_text(cdp, '取消')
        return 'confirm-disabled'
    q = json.loads(ok)
    cdp.click_at(q['x'], q['y'])
    time.sleep(2.0)
    now = cdp.js("""(() => {const e=document.querySelector('.publish-header-volume-name');
        return e?e.innerText.trim():'';})()""")
    return 'ok' if now == vol else 'mismatch:%s' % now


def save_draft(cdp):
    if not click_text(cdp, '存草稿', 'button,div,span,a'):
        return False
    t0 = time.time()
    while time.time() - t0 < 90:
        time.sleep(1.0)
        t = cdp.js('document.body.innerText') or ''
        if '已保存' in t:
            return True
        if '版本冲突' in t:
            click_text(cdp, '继续编辑本地', 'button,div,span,a')
            time.sleep(2.0)
    return False


# ---------------------------------------------------------------- 主流程

def upload_one(cdp, ch, vol):
    err = open_new_draft(cdp)
    if err:
        return {'ok': False, 'error': err}

    got_num = set_input(cdp, NUM_EXPR, ch['num'])
    time.sleep(0.5)
    got_title = set_input(cdp, TITLE_EXPR, ch['title'])
    time.sleep(0.8)

    body = inject_body(cdp, ch['paras'])
    vres = set_volume(cdp, vol)
    saved = save_draft(cdp)

    read = json.loads(cdp.js("""(() => {
      const n=%s; const t=%s;
      return JSON.stringify({num:n?n.value:'', title:t?t.value:''});
    })()""" % (NUM_EXPR, TITLE_EXPR)) or '{}')
    return {'ok': saved and body['ok'], 'num': read.get('num') or got_num,
            'title': read.get('title') or got_title, 'body': body,
            'vol': vres, 'saved': saved}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--book-id', default=CFG.book_id(),
                    help='可省，写在 config.json 的 book_id / 环境变量 FANQIE_BOOK_ID')
    ap.add_argument('--from', dest='frm', type=int, required=True)
    ap.add_argument('--to', dest='to', type=int, required=True)
    ap.add_argument('--file', help='合并版 txt')
    ap.add_argument('--dir', help='单章 txt 目录')
    ap.add_argument('--volume', default=CFG.get('volume') or '',
                    help='目标分卷全名，如「第三卷：中层管理」')
    ap.add_argument('--interval', type=int, default=int(CFG.get('interval') or 45))
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--force', action='store_true', help='后台已有同章号也重传')
    ap.add_argument('--headed', action='store_true', help='开有头浏览器（首次登录用）')
    a = ap.parse_args()
    if not a.book_id:
        ap.error('缺 bookId：命令行给 --book-id，或写进 config.json / FANQIE_BOOK_ID')

    if not a.file and not a.dir:
        raise SystemExit('要么 --file，要么 --dir')

    chapters = (parse_file(a.file, a.frm, a.to) if a.file
                else parse_dir(a.dir, a.frm, a.to))
    if not chapters:
        raise SystemExit('没有解析到任何章节，检查 --from/--to 与文件命名')
    for c in chapters:
        print('[解析] 第%d章 %s | 段 %d' % (c['num'], c['title'], len(c['paras'])))
    if a.dry_run:
        print('--dry-run，不写后台')
        return 0

    C.launch(headless=not a.headed)
    cdp = C.connect()
    rc = 0
    try:
        manage_home(cdp, a.book_id)
        url = cdp.js('location.href') or ''
        if '/login' in url:
            print('!! 掉登录，请用 --headed 打开后扫码：', url)
            return 2
        existing = draft_list(cdp)
        have = set()
        for name, _ in existing:
            m = re.match(r'^第\s*(\d{1,4})\s*章', name)
            if m:
                have.add(int(m.group(1)))
        print('后台草稿箱 %d 条，已存在章号：%s' % (len(existing), sorted(have)))

        for ch in chapters:
            if ch['num'] in have and not a.force:
                print('[跳过] 第%d章 已在草稿箱' % ch['num'])
                continue
            print('\n=== 上传 第%d章 %s ===' % (ch['num'], ch['title']))
            r = upload_one(cdp, ch, a.volume)
            print('  表单: %s' % {k: r.get(k) for k in ('num', 'title')})
            print('  正文: %s' % r['body'])
            print('  切卷: %s | 存草稿: %s' % (r['vol'], r['saved']))
            if not r['ok']:
                print('  !! 本章未达标，停止')
                rc = 4
                break
            # 回读确认
            manage_home(cdp, a.book_id)
            names = [n for n, _ in draft_list(cdp)]
            hit = [n for n in names if re.match(r'^第\s*%d\s*章' % ch['num'], n)]
            print('  回读: %s' % (hit[0] if hit else '未出现'))
            if not hit:
                print('  !! 草稿箱未见本章，停止')
                rc = 6
                break
            have.add(ch['num'])
            if a.interval:
                time.sleep(a.interval)
    finally:
        C.close_browser(cdp)
    print('\n退出码:', rc)
    return rc


if __name__ == '__main__':
    sys.exit(main() or 0)
