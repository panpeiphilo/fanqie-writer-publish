#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fanqie_config.py — 全脚本共用的配置读取（零依赖）

为什么要有这个文件：登录态存在 Chrome 的持久 profile 里，而 profile 到底放在哪，
每台机器都不一样（默认 `~/.fanqie-profile`，但很多人把它放在项目目录旁边）。
把路径硬编码在脚本里或者每次敲环境变量都容易忘，忘了的后果是**静默跳登录页、
读到的卷列表是空的**，排查起来很费时间。

取值优先级（高 → 低）
    1. 环境变量           FANQIE_PROFILE / FANQIE_BOOK_ID / CHROME_PATH / FANQIE_CDP_PORT / FANQIE_CONFIG
    2. 配置文件 config.json
    3. 自动发现（仅当上面给的位置里没有登录态时）
    4. 内置默认值

配置文件查找位置（第一个存在的生效）
    $FANQIE_CONFIG
    ./config.json                    ← 当前工作目录（在书稿目录里跑就放这里）
    <skill根目录>/config.json        ← 与 SKILL.md 同级（推荐）
    ~/.fanqie/config.json

自检
    python scripts/fanqie_config.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)

DEFAULTS = {
    'profile': '~/.fanqie-profile',
    'book_id': '',
    'chrome': '',
    'cdp_port': 9333,
    'volume': '',
    'interval': 45,
}

ENV_MAP = {
    'profile': 'FANQIE_PROFILE',
    'book_id': 'FANQIE_BOOK_ID',
    'chrome': 'CHROME_PATH',
    'cdp_port': 'FANQIE_CDP_PORT',
    'volume': 'FANQIE_VOLUME',
    'interval': 'FANQIE_INTERVAL',
}


# ------------------------------------------------------------------ 基础工具

def _expand(p):
    """展开 ~ 与环境变量；顺便把 Windows 反斜杠统一成正斜杠（Chrome 也认）。"""
    if not p:
        return ''
    return os.path.expanduser(os.path.expandvars(str(p)))


def config_path():
    """返回实际生效的 config.json 路径；都没有则返回 None。"""
    env = os.environ.get('FANQIE_CONFIG')
    cands = ([_expand(env)] if env else []) + [
        os.path.join(os.getcwd(), 'config.json'),
        os.path.join(SKILL_ROOT, 'config.json'),
        os.path.join(os.path.expanduser('~'), '.fanqie', 'config.json'),
    ]
    for p in cands:
        if p and os.path.isfile(p):
            return p
    return None


def _load_file():
    path = config_path()
    if not path:
        return {}, None
    try:
        with open(path, encoding='utf-8') as f:
            raw = json.load(f)
    except Exception as e:                                   # noqa: BLE001
        print('[警告] 配置文件读不了，已忽略：%s（%s）' % (path, e), file=sys.stderr)
        return {}, path
    data = {k: v for k, v in raw.items() if not k.startswith('_')}
    return data, path


def _cast(key, val):
    if val is None or val == '':
        return None
    try:
        if key in ('cdp_port', 'interval'):
            return int(val)
    except (TypeError, ValueError):
        return None
    return val


# ------------------------------------------------------------------ 自动发现

def profile_usable(path):
    """目录里有没有 Chrome 的登录态（Cookies 落盘才算）。"""
    if not path or not os.path.isdir(path):
        return False
    for rel in ('Default/Network/Cookies', 'Default/Cookies',
                'Network/Cookies', 'Cookies'):
        if os.path.isfile(os.path.join(path, *rel.split('/'))):
            return True
    # 建过 profile 但还没登录过：目录存在且非空也算「这是个 profile」
    try:
        return bool(os.listdir(path))
    except OSError:
        return False


def discover_profile():
    """在常见位置找一个真正带登录态的 .fanqie-profile。

    返回 (路径, 说明) 或 (None, '')。只在显式配置无效时调用。
    """
    cands = []
    cwd = os.getcwd()
    for base in (cwd, os.path.dirname(cwd)):
        cands.append(os.path.join(base, '.fanqie-profile'))
    cands.append(os.path.join(os.path.expanduser('~'), '.fanqie-profile'))
    cands.append(os.path.join(SKILL_ROOT, '.fanqie-profile'))

    seen, hits = set(), []
    for p in cands:
        p = os.path.normpath(p)
        if p in seen or not profile_usable(p):
            continue
        seen.add(p)
        hits.append(p)
    if not hits:
        return None, ''
    # 优先带 Cookies 的（能直接用），否则取第一个
    for p in hits:
        if profile_usable(p) and os.path.isfile(os.path.join(p, 'Default', 'Network', 'Cookies')):
            return p, '自动发现（含登录态）'
    return hits[0], '自动发现（目录存在，但未见 Cookies，可能需重新登录）'


# ------------------------------------------------------------------ 对外接口

_CACHE = {}


def get(key, default=None):
    """按优先级取一个配置项。"""
    if key in _CACHE:
        return _CACHE[key]

    val = None
    # 1) 环境变量
    env = ENV_MAP.get(key)
    if env:
        val = _cast(key, os.environ.get(env))
    # 2) 配置文件
    if val is None:
        data, _ = _load_file()
        val = _cast(key, data.get(key))
    # 3) profile 特殊照顾：显式值无效时自动发现
    if val is None and key == 'profile':
        found, why = discover_profile()
        if found:
            _CACHE['_profile_source'] = why
            val = found
    # 4) 默认值
    if val is None:
        val = default if default is not None else DEFAULTS.get(key)

    if key in ('profile', 'chrome') and val:
        val = _expand(val)
    _CACHE[key] = val
    return val


def profile():
    return get('profile') or os.path.join(os.path.expanduser('~'), '.fanqie-profile')


def book_id():
    return str(get('book_id') or '')


def reset():
    """改过环境变量或配置文件后想重新读，调这个。"""
    _CACHE.clear()


# ------------------------------------------------------------------ 自检

def main():
    data, path = _load_file()
    print('配置文件   : %s' % (path or '(未找到，全部走默认/环境变量)'))
    print('skill 根目录: %s' % SKILL_ROOT)
    print('当前目录   : %s' % os.getcwd())
    print('-' * 62)
    rows = []
    for k in DEFAULTS:
        v = get(k)                    # 先取值，自动发现的来源标记由 get() 写入缓存
        env = ENV_MAP.get(k)
        src = '默认'
        if env and os.environ.get(env):
            src = '环境变量 %s' % env
        elif k in data and _cast(k, data.get(k)) is not None:
            src = 'config.json'
        elif k == 'profile' and _CACHE.get('_profile_source'):
            src = _CACHE['_profile_source']
        rows.append((k, v, src))

    for k, v, src in rows:
        if k == 'chrome' and not v:
            try:
                import cdp_client  # noqa: PLC0415
                v = cdp_client.find_chrome() + '  (自动探测)'
            except Exception:                              # noqa: BLE001
                v = '(未找到，需设 CHROME_PATH)'
        print('%-10s: %-52s [%s]' % (k, v, src))

    print('-' * 62)
    p = profile()
    if not os.path.isdir(p):
        print('❌ profile 目录不存在：%s' % p)
        print('   → 首次使用先跑：python scripts/fanqie_upload_cdp.py ... --headed 扫码登录')
        return 1
    if profile_usable(p):
        print('✅ profile 可用：%s' % p)
        return 0
    print('⚠️  profile 存在但未见登录态：%s' % p)
    print('   → 跑一次 --headed 扫码登录即可')
    return 1


if __name__ == '__main__':
    sys.exit(main())
