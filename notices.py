"""Read-only update discovery and per-client, per-batch notification receipts."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import uuid

import online as o
import updater as u


def validate_news(value, packages):
    if value is None:
        return {}
    if not isinstance(value, dict) or set(value) != {'id', 'changes', 'descriptions'}:
        raise u.SkipUpdate('更新說明格式無效')
    if not isinstance(value['id'], str) or not 1 <= len(value['id']) <= 80:
        raise u.SkipUpdate('更新說明版本無效')
    changes = value['changes']
    descriptions = value['descriptions']
    if (not isinstance(changes, list) or len(changes) > 20 or
            any(not isinstance(x, str) or not 1 <= len(x) <= 300 for x in changes) or
            not isinstance(descriptions, dict) or
            any(k not in {p.key for p in packages} or not isinstance(v, str) or
                not 1 <= len(v) <= 200 for k, v in descriptions.items())):
        raise u.SkipUpdate('更新說明內容無效')
    return value


@dataclass(frozen=True)
class Notice:
    identity: str
    minimum_app: str
    revision: str
    packages: tuple
    news: dict


def discover():
    # Only public JSON is read. No extraction, baseline or AddOns writes here.
    raw = o.download(o.asset(o.release(o.CATALOG_TAG), 'catalog.json'), 512 * 1024)
    data, packages = o.parse_catalog(raw, check_minimum=False)
    news = validate_news(data.get('news'), packages)
    return Notice(hashlib.sha256(raw).hexdigest(), data['minimum_app'], data['revision'], packages, news)


def cached():
    identity = (o.CACHE / 'active.txt').read_text(encoding='ascii')
    catalog = o._cached(identity)
    data, packages = o.parse_catalog((catalog.customizations.parent / 'catalog.json').read_bytes())
    return Notice(identity, data['minimum_app'], data['revision'], packages, validate_news(data.get('news'), packages))


def missing_packages(notice, game):
    addons = game / '_forever_/Interface/AddOns'
    return tuple(p for p in notice.packages if not (addons / p.anchor).is_dir())


def pending(notice, game):
    if missing_packages(notice, game):
        return True
    try:
        state = json.loads((u.baseline_location(game) / '.catalog-state.json').read_text(encoding='utf-8'))
        return any(state.get(p.key) != notice.identity for p in notice.packages) or state.get('hub') != notice.identity
    except (OSError, ValueError, AttributeError):
        return True


def receipt_key(game, notice=None, app_update=None):
    client = hashlib.sha256(str(game.resolve()).casefold().encode()).hexdigest()[:20]
    batch = (notice.news.get('id') or notice.identity) if notice else ''
    version = app_update['version'] if app_update else ''
    return f'{client}:{batch}:{version}'


def seen(key):
    try:
        value = json.loads((u.APP / 'notice-state.json').read_text(encoding='utf-8'))
        return isinstance(value, list) and key in value
    except (OSError, ValueError):
        return False


def acknowledge(key):
    path = u.APP / 'notice-state.json'
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, list):
            value = []
    except (OSError, ValueError):
        value = []
    value = [x for x in value if isinstance(x, str) and x != key][-199:] + [key]
    temporary = path.with_name(f'.notice-{uuid.uuid4().hex}.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def body(notice, game, app_update=None):
    lines = []
    if app_update:
        lines += [f'管理器程式有新版 v{app_update["version"]}。', '更新後會自動重新開啟，再接著更新遊戲插件。', '']
    if notice:
        lines += [f'整合包更新 · {notice.revision}', '']
        missing = missing_packages(notice, game)
        if missing:
            lines += ['這台電腦可新增的插件']
            for p in missing:
                description = notice.news.get('descriptions', {}).get(p.key, '')
                lines += [f'・{p.label}' + (f'：{description}' if description else '')]
            lines += ['']
        if notice.news.get('changes'):
            lines += ['本次改善'] + ['・' + x for x in notice.news['changes']] + ['']
        if o.app_order(notice.minimum_app) > o.app_order(o.APP_VERSION):
            lines += ['這批整合內容需要先更新管理器程式。', '']
        elif not pending(notice, game):
            lines += ['這台電腦已同步本批整合內容。', '']
    else:
        lines += ['暫時無法取得整合包更新說明，可稍後再查詢。', '']
    return '\n'.join(lines + ['安裝或更新遊戲插件前，請先完全退出遊戲。'])
