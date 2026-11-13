#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fanqie_volume.py — 番茄后台分卷：查看 / 新建 / 改章归属

后台的分卷入口只有一个是真的：**章节编辑页顶部点卷名**弹出的
`.serial-modal.editor-volume`。章节管理页那个「编辑分卷」只能改名/删，不能建。

建卷的真实流程（2026-11 实测，前三种常见做法都无效）
  点「新建分卷」→ 列表顶部出现编辑态项
    ├ 前缀「第四卷：」由后台**自动编号**，只需输入卷名正文（限 16 字）
    ├ 点绿勾 `i.tomato-confirm`   ← 唯一会调接口的动作
    └ 点红叉 `i.tomato-cancel`    ← 放弃
  点底部「取消」关窗（不改当前章节归属）

  ✗ 输入完整「第四卷：合伙人」再按 Enter：只在本地态，关窗即丢
  ✗ 点底部「确定」：新建态下是 disabled，其语义是「把当前章节归到选中卷」

用法
  python scripts/fanqie_volume.py --book-id X --list
  python scripts/fanqie_volume.py --book-id X --create 合伙人 行业寒冬
  python scripts/fanqie_volume.py --book-id X --assign 148="第三卷：中层管理"

平台限制：**不允许两个空卷并存**，新建第二卷会返回
`{"code":-4054,"message":"暂不支持创建多个无章节的分卷"}`。
要让卷 N 建好后再建卷 N+1，必须先给卷 N 挂上至少一章。
"""
import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdp_client as C  # noqa: E402

MANAGE = 'https://fanqienovel.com/main/writer/chapter-manage/%s'
EDIT = 'https://fanqienovel.com/main/writer/%s/publish/%s?enter_from=newdraft'


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


def click_expr(cdp, expr):
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


# ---------------------------------------------------------------- 读卷列表

def list_volumes(cdp, book_id):
    """从章节管理页的「卷筛选下拉」读——这是服务端数据，能确认真实落库"""
    cdp.goto(MANAGE % book_id, settle=4.0,
             wait_js="!!document.querySelector('.serial-select')", timeout=90)
    for _ in range(2):
        if not click_text(cdp, '我知道了', 'button,div,span,a'):
            break
        time.sleep(1.0)
    cur = cdp.js("""(() => {const e=document.querySelector('.serial-select .byte-select-view-value');
        return e?e.innerText.trim():'';})()""")
    if not click_expr(cdp, "document.querySelector('.serial-select')"):
        return cur, []
    time.sleep(2.0)
    b = cdp.js(r"""(() => {
      const out=[];
      for (const e of document.querySelectorAll('[class*=option],[role=option],li,div')) {
        if (e.children.length>1) continue;
        const t=(e.innerText||'').trim();
        if (!t || t.length>30) continue;
        if (!/^第.+卷|^全部/.test(t)) continue;
        const r=e.getBoundingClientRect();
        if (r.width<4||r.height<4) continue;
        out.push(t);
      }
      return JSON.stringify([...new Set(out)]);
    })()""")
    vols = [v for v in json.loads(b or '[]') if v.startswith('第') and '卷' in v]
    # 关掉下拉
    click_text(cdp, '我知道了')
    return cur, vols


# ---------------------------------------------------------------- 进入编辑页

def enter_editor(cdp, book_id):
    """随便找一个章节/草稿的编辑页——建卷只能在这里做"""
    cdp.goto(MANAGE % book_id, settle=4.0,
             wait_js="!!document.querySelector('table')", timeout=90)
    for _ in range(2):
        if not click_text(cdp, '我知道了', 'button,div,span,a'):
            break
        time.sleep(1.0)

    # 1) 章节管理列表里的章节（href 含 /preview/{bookId}&{chapterId}）
    href = cdp.js(r"""(() => {
      const a=document.querySelector('a[href*="/preview/"]');
      return a?a.getAttribute('href'):'';})()""")
    if href and '&' in href:
        cid = href.split('&')[-1].split('?')[0]
        cdp.goto(EDIT % (book_id, cid), settle=4.0,
                 wait_js="!!document.querySelector('.publish-header-volume-wrap')", timeout=90)
        return True

    # 2) 没有章节（新书）：进草稿箱新建一个空白草稿
    click_text(cdp, '草稿箱', 'div')
    time.sleep(4.0)
    if click_text(cdp, '新建草稿', 'button,div,span,a'):
        t0 = time.time()
        while time.time() - t0 < 45:
            time.sleep(1.0)
            if cdp.js("!!document.querySelector('.publish-header-volume-wrap')") is True:
                time.sleep(1.5)
                return True
    return False


def open_volume_modal(cdp):
    if not click_expr(cdp, "document.querySelector('.publish-header-volume-wrap')"):
        return False
    t0 = time.time()
    while time.time() - t0 < 20:
        time.sleep(0.5)
        if cdp.js("!!document.querySelector('.serial-modal.editor-volume')") is True:
            return True
    return False


def modal_volumes(cdp):
    b = cdp.js(r"""(() => {
      const root=document.querySelector('.serial-modal.editor-volume');
      if(!root) return '[]';
      const out=[];
      for (const it of root.querySelectorAll('.editor-volume-list-item')) {
        out.push({text:(it.innerText||'').replace(/\s+/g,' ').trim(),
                  editing: !!it.querySelector('input')});
      }
      return JSON.stringify(out);
    })()""")
    return json.loads(b or '[]')


# ---------------------------------------------------------------- 建卷

def create_volume(cdp, name):
    """建一卷，返回 (成功?, 说明)。name 不带「第N卷：」前缀。"""
    if not open_volume_modal(cdp):
        return False, '卷弹窗未打开'
    time.sleep(1.0)
    if not click_expr(cdp, "document.querySelector('.editor-volume-footer-add-volume')"):
        return False, '「新建分卷」不可点（可能已达卷数上限或当前有未提交的编辑态）'
    time.sleep(1.8)

    box = cdp.js(r"""(() => {
      const e=document.querySelector('.editor-volume-list-item input');
      if(!e) return '';
      const r=e.getBoundingClientRect();
      return JSON.stringify({x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)});
    })()""")
    if not box:
        return False, '新建态输入框未出现'
    p = json.loads(box)
    cdp.click_at(p['x'], p['y'])
    time.sleep(0.3)
    cdp.insert_text(name)
    time.sleep(0.9)
    val = cdp.js("""(() => {const e=document.querySelector('.editor-volume-list-item input');
        return e?e.value:'';})()""")
    if val != name:
        return False, '输入回读不一致：%r' % val

    # 绿勾：唯一会调接口的按钮。偶发点不中，重试并轮询列表
    ok = False
    for _ in range(3):
        if not click_expr(cdp, "document.querySelector('i.tomato-confirm')"):
            break
        t0 = time.time()
        while time.time() - t0 < 6:
            time.sleep(0.6)
            if any(name in v['text'] and not v['editing'] for v in modal_volumes(cdp)):
                ok = True
                break
        if ok:
            break
    # 关窗（不改当前章节归属）
    click_text(cdp, '取消')
    time.sleep(1.2)
    if not ok:
        return False, ('绿勾未生效。常见原因：已有另一个空卷（平台返回 -4054 '
                       '「暂不支持创建多个无章节的分卷」），需先给上一个空卷挂章节')
    return True, '已建'


# ---------------------------------------------------------------- 改章归属

def assign(cdp, book_id, vol, chapter_key):
    """把某个草稿/章节改到指定卷。chapter_key 为章号（数字串）。"""
    # 回管理页找该章的编辑页 id
    cdp.goto(MANAGE % book_id, settle=4.0,
             wait_js="!!document.querySelector('table')", timeout=90)
    for _ in range(2):
        if not click_text(cdp, '我知道了', 'button,div,span,a'):
            break
        time.sleep(1.0)
    click_text(cdp, '草稿箱', 'div')
    time.sleep(4.5)
    href = cdp.js(r"""(() => {
      const want=%s;
      for (const tr of document.querySelectorAll('table tr')) {
        if ((tr.textContent||'').indexOf(want)<0) continue;
        const a=tr.querySelector('a[href*="/preview/"]');
        if (a) return a.getAttribute('href');
      }
      return '';
    })()""" % json.dumps('第%s章' % chapter_key))
    if not href or '&' not in href:
        return 'chapter-not-found'
    cid = href.split('&')[-1].split('?')[0]
    cdp.goto(EDIT % (book_id, cid), settle=4.0,
             wait_js="!!document.querySelector('.publish-header-volume-wrap')", timeout=90)
    time.sleep(1.5)
    if not open_volume_modal(cdp):
        return 'modal-fail'
    time.sleep(1.0)
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
    if now != vol:
        return 'mismatch:%s' % now
    if not click_text(cdp, '存草稿', 'button,div,span,a'):
        return 'saved-vol-but-not-persisted'
    time.sleep(3.0)
    return 'ok'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--book-id', required=True)
    ap.add_argument('--list', action='store_true', help='读服务端卷列表')
    ap.add_argument('--create', nargs='+', metavar='名称', help='新建卷（只给卷名，后台自动编号）')
    ap.add_argument('--assign', nargs='+', metavar='章号=卷名', help='把草稿改到指定卷')
    ap.add_argument('--headed', action='store_true')
    a = ap.parse_args()
    if not (a.list or a.create or a.assign):
        ap.error('至少给一个动作：--list / --create / --assign')

    C.launch(headless=not a.headed)
    cdp = C.connect()
    rc = 0
    try:
        if a.list:
            cur, vols = list_volumes(cdp, a.book_id)
            print('当前筛选:', cur)
            print('服务端卷列表:')
            for v in vols:
                print('  -', v)

        if a.create:
            if not enter_editor(cdp, a.book_id):
                print('!! 进不了章节编辑页（建卷只能在这里做）')
                return 3
            print('编辑页:', cdp.js('location.href'))
            for name in a.create:
                if name.startswith('第') and '卷' in name:
                    print('!! 卷名不要带「第N卷：」前缀，后台会自动编号：', name)
                    rc = 2
                    break
                ok, msg = create_volume(cdp, name)
                print('[建卷] %s → %s（%s）' % (name, '成功' if ok else '失败', msg))
                if not ok:
                    rc = 4
                    break
                enter_editor(cdp, a.book_id)   # 回到编辑页，准备建下一卷

        if a.assign:
            for expr in a.assign:
                if '=' not in expr:
                    print('!! --assign 格式应为 章号=卷名：', expr)
                    rc = 2
                    continue
                num, vol = expr.split('=', 1)
                res = assign(cdp, a.book_id, vol.strip(), num.strip())
                print('[改卷] 第%s章 → %s：%s' % (num, vol, res))
                if res != 'ok':
                    rc = 5

        if a.create or a.assign:
            cur, vols = list_volumes(cdp, a.book_id)
            print('\n=== 服务端最终卷列表 ===')
            for v in vols:
                print('  -', v)
    finally:
        C.close_browser(cdp)
    print('退出码:', rc)
    return rc


if __name__ == '__main__':
    sys.exit(main() or 0)
