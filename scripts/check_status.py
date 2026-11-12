#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_status.py — 核对番茄作家后台的章节状态（已发布 / 待发布 / 草稿）

用途
  上传完成后核对：哪些章进了草稿箱、哪些已排定时、字数对不对。
  也可作为「上传前体检」，确认后台到底停在第几章。

用法
  python scripts/check_status.py --book-id 1234567890
  python scripts/check_status.py --book-id 1234567890 --csv status.csv --last 20
  python scripts/check_status.py --book-id 1234567890 --dir ./chapters   # 顺带比对本地字数
"""
import argparse
import csv
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fanqie_upload import ab, ev, ev_json, wait_bool, BOOK_MANAGE, HEAD_RE, parse_single  # noqa: E402

GRAB = """(() => {
  const rows = [...document.querySelectorAll('table tr')].filter(tr => tr.getClientRects().length > 0).map(tr => {
    const td = [...tr.querySelectorAll('td')].map(c => c.innerText.replace(/\\s+/g, ' ').trim());
    return td;
  }).filter(td => td.length >= 3 && /^第\\s*\\d+\\s*章/.test(td[0] || ''));
  return JSON.stringify(rows);
})()"""

DRAFT_GRAB = """(() => {
  const rows = [...document.querySelectorAll('table tr')].filter(tr => tr.getClientRects().length > 0).map(tr => {
    const td = [...tr.querySelectorAll('td')].map(c => c.innerText.replace(/\\s+/g, ' ').trim());
    return td;
  }).filter(td => td.length <= 4 && /^第\\s*\\d+\\s*章/.test(td[0] || ''));
  return JSON.stringify(rows);
})()"""


def collect(book_id):
    ab(['open', BOOK_MANAGE % book_id], timeout=120)
    if not wait_bool("""!!([...document.querySelectorAll('[role="tab"]')].find(t=>t.innerText.includes('草稿箱')))""", timeout=40):
        sys.exit('页面未就绪，确认已登录 fanqienovel.com')

    out = []
    # 章节管理（已发布 + 待发布）
    ev("""(() => {const t=[...document.querySelectorAll('[role="tab"]')].find(x=>x.innerText.includes('章节管理'));
            if(t) t.click(); return 'ok';})()""")
    import time
    time.sleep(2.5)
    for row in ev_json(GRAB) or []:
        m = re.match(r'^第\s*(\d+)\s*章', row[0])
        if not m:
            continue
        out.append({'num': int(m.group(1)), 'title': re.sub(r'^第\s*\d+\s*章\s*', '', row[0]),
                    'words': row[1], 'status': row[3] if len(row) > 3 else '',
                    'time': row[4] if len(row) > 4 else '', 'src': 'chapters'})

    # 草稿箱
    ev("""(() => {const t=[...document.querySelectorAll('[role="tab"]')].find(x=>x.innerText.includes('草稿箱'));
            if(t) t.click(); return 'ok';})()""")
    time.sleep(2.5)
    for row in ev_json(DRAFT_GRAB) or []:
        m = re.match(r'^第\s*(\d+)\s*章', row[0])
        if not m:
            out.append({'num': None, 'title': row[0], 'words': row[1] if len(row) > 1 else '',
                        'status': '草稿', 'time': row[-1] if row else '', 'src': 'drafts'})
            continue
        out.append({'num': int(m.group(1)), 'title': re.sub(r'^第\s*\d+\s*章\s*', '', row[0]),
                    'words': row[1] if len(row) > 1 else '', 'status': '草稿',
                    'time': row[-1] if row else '', 'src': 'drafts'})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--book-id', required=True)
    ap.add_argument('--csv', help='导出 CSV 路径')
    ap.add_argument('--last', type=int, default=15, help='仅显示最大章号起往前 N 条，默认 15')
    ap.add_argument('--dir', help='本地单章目录，用于比对字数')
    a = ap.parse_args()

    rows = collect(a.book_id)
    if not rows:
        sys.exit('没抓到章节行，可能是页面结构变化或掉登录')

    nums = [r['num'] for r in rows if r['num']]
    print('共 %d 条记录，最大章号：第%d章' % (len(rows), max(nums) if nums else 0))

    local = {}
    if a.dir:
        for f in sorted(os.listdir(a.dir)):
            if f.endswith('.txt'):
                try:
                    c = parse_single(os.path.join(a.dir, f))
                    if c:
                        local[c['num']] = sum(len(x) for x in c['body'])
                except Exception:
                    pass

    rows.sort(key=lambda r: (r['num'] if r['num'] else 10 ** 6))
    show = [r for r in rows if r['num'] and r['num'] >= max(nums) - a.last + 1] if nums else rows[:a.last]

    print('\n%-8s %-28s %-8s %-10s %-18s %s' % ('章号', '标题', '平台字数', '状态', '定时/时间', '本地字数'))
    for r in show:
        n = r['num']
        lw = ('%d' % local[n]) if (a.dir and n in local) else ''
        print('%-8s %-28s %-8s %-10s %-18s %s'
              % ('第%d章' % n if n else '—', r['title'][:26], r['words'], r['status'], r['time'], lw))

    if a.csv:
        with io.open(a.csv, 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.writer(f)
            w.writerow(['章号', '标题', '平台字数', '状态', '时间', '本地字数'])
            for r in rows:
                n = r['num']
                w.writerow([n or '', r['title'], r['words'], r['status'], r['time'],
                            local.get(n, '') if a.dir else ''])
        print('\n已导出：%s' % a.csv)


if __name__ == '__main__':
    main()
