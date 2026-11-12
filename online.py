"""Versioned, verified GitHub release data; never import downloaded Python code."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import tempfile
import uuid

import updater as u

APP_VERSION = "1.1.3"
CATALOG_MIN_APP = "1.1.0"
REPOSITORY = "littleblackmann/wow-forever-addon-updater"
CACHE = u.APP / "online"
CATALOG_TAG = "catalog"
EXCLUDED = {"rxpguides", "amobicompanion", "foreverquestpins"}


@dataclass(frozen=True)
class Catalog:
    packages: tuple
    customizations: Path
    identity: str | None
    note: str


def release(tag: str | None = None):
    suffix = f"tags/{tag}" if tag else "latest"
    data = u.github_release_data(REPOSITORY, suffix)
    if data.get("draft") or data.get("prerelease") or not re.fullmatch(r"[A-Za-z0-9._-]+", data.get("tag_name", "")):
        raise u.SkipUpdate("線上發行版本資料無效")
    if tag and data["tag_name"] != tag:
        raise u.SkipUpdate("線上清單標籤不符")
    return data


def asset(data, name: str):
    items = [a for a in data.get("assets", []) if a.get("name") == name]
    if len(items) != 1:
        raise u.SkipUpdate(f"線上發行檔缺少 {name}")
    item = items[0]
    expected = f"https://github.com/{REPOSITORY}/releases/download/{data['tag_name']}/{name}"
    if item.get("browser_download_url") != expected or not isinstance(item.get("size"), int):
        raise u.SkipUpdate("發行檔來源或大小無效")
    return item


def download(item, limit: int, sha256: str | None = None):
    if not 0 < item["size"] <= limit:
        raise u.SkipUpdate("線上更新檔超過大小上限")
    raw = u.fetch(item["browser_download_url"], limit)
    digest = hashlib.sha256(raw).hexdigest()
    if len(raw) != item["size"] or (sha256 and digest != sha256):
        raise u.SkipUpdate("線上更新檔完整性驗證失敗")
    if item.get("digest") and item["digest"] != "sha256:" + digest:
        raise u.SkipUpdate("GitHub 發行檔雜湊不符")
    return raw


def parse_catalog(raw: bytes):
    data = json.loads(raw)
    if data.get("schema") != 1 or not isinstance(data.get("revision"), str) or len(data["revision"]) > 80:
        raise u.SkipUpdate("不支援的整合清單格式")
    if app_order(data.get("minimum_app", "")) > app_order(APP_VERSION):
        raise u.SkipUpdate("線上清單需要新版管理器，請先按「更新管理器介面（UI）」")
    rows = data.get("packages")
    if not isinstance(rows, list) or not 0 < len(rows) <= 100:
        raise u.SkipUpdate("整合清單的插件數量無效")
    packages, keys, folders = [], set(), set()
    for row in rows:
        if set(row) != {"key", "label", "anchor", "source", "archive", "folders"}:
            raise u.SkipUpdate("整合清單的插件欄位無效")
        if not isinstance(row["folders"], list) or len(row["folders"]) > 50:
            raise u.SkipUpdate("整合清單的模組欄位無效")
        for name in [row["key"], row["anchor"], *row["folders"]]:
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", name):
                raise u.SkipUpdate("整合清單含有無效資料夾")
        if not isinstance(row["label"], str) or len(row["label"]) > 100:
            raise u.SkipUpdate("整合清單的名稱無效")
        if not isinstance(row["source"], str) or not re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+", row["source"]):
            raise u.SkipUpdate("整合清單的作者來源無效")
        if not isinstance(row["archive"], str) or not 0 < len(row["archive"]) <= 500:
            raise u.SkipUpdate("整合清單的ZIP格式無效")
        re.compile(row["archive"])
        names = {n.casefold() for n in [row["anchor"], *row["folders"]]}
        if (row["key"] in keys or folders & names or names & EXCLUDED or "xiaoheiaddonhub" in names
                or len(names) != 1 + len(row["folders"])):
            raise u.SkipUpdate("整合清單含有重複或已排除的插件")
        keys.add(row["key"])
        folders.update(names)
        packages.append(u.Package(**dict(row, folders=tuple(row["folders"]))))
    payload = data.get("customizations", {})
    if (payload.get("name") != "customizations.zip" or not re.fullmatch(r"[0-9a-f]{64}", payload.get("sha256", ""))):
        raise u.SkipUpdate("整合檔雜湊資料無效")
    return data, tuple(packages)


def unpacked_files(archive: Path, packages):
    files = u.read_zip(archive, ("customizations",))
    allowed = {"customizations/hub.zip", "customizations/manifest.json"}
    allowed |= {f"customizations/{p.key}/{name}.zip" for p in packages for name in ("base", "local")}
    if not files or any(path not in allowed for path, _ in files.values()):
        raise u.SkipUpdate("整合檔包含不允許的內容")
    if "customizations/hub.zip" not in files:
        raise u.SkipUpdate("整合檔缺少總入口")
    return files


def _cached(identity: str):
    if not re.fullmatch(r"[0-9a-f]{64}", identity):
        raise u.SkipUpdate("本機整合快取資料無效")
    folder = CACHE / identity
    raw = (folder / "catalog.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != identity:
        raise u.SkipUpdate("本機整合清單驗證失敗")
    data, packages = parse_catalog(raw)
    archive = folder / "customizations.zip"
    if hashlib.sha256(archive.read_bytes()).hexdigest() != data["customizations"]["sha256"]:
        raise u.SkipUpdate("本機整合檔驗證失敗")
    for relative, contents in unpacked_files(archive, packages).values():
        if (folder / relative).read_bytes() != contents:
            raise u.SkipUpdate("已解壓的整合檔遭到變更")
    return Catalog(packages, folder / "customizations", identity, "整合清單 " + data["revision"])


def sync_catalog() -> Catalog:
    try:
        data = release(CATALOG_TAG)
        raw = download(asset(data, "catalog.json"), 512 * 1024)
        catalog, packages = parse_catalog(raw)
        identity = hashlib.sha256(raw).hexdigest()
        CACHE.mkdir(parents=True, exist_ok=True)
        destination = CACHE / identity
        if not destination.exists():
            payload = download(asset(data, "customizations.zip"), 30 * 1024**2, catalog["customizations"]["sha256"])
            with tempfile.TemporaryDirectory(prefix="catalog-", dir=CACHE) as tmp:
                folder = Path(tmp) / "ready"
                folder.mkdir()
                (folder / "catalog.json").write_bytes(raw)
                archive = folder / "customizations.zip"
                archive.write_bytes(payload)
                for relative, contents in unpacked_files(archive, packages).values():
                    out = folder / relative
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(contents)
                try:
                    folder.rename(destination)
                except FileExistsError:
                    pass  # Another copy completed the same verified snapshot.
        result = _cached(identity)
        pointer = CACHE / f".{uuid.uuid4().hex}.tmp"
        pointer.write_text(identity, encoding="ascii")
        pointer.replace(CACHE / "active.txt")
        return result
    except Exception as exc:
        try:
            previous = _cached((CACHE / "active.txt").read_text(encoding="ascii"))
            return Catalog(previous.packages, previous.customizations, previous.identity,
                           f"離線沿用 {previous.note}｜{u.process_error(exc)}")
        except Exception:
            return Catalog(u.PACKAGES, u.CUSTOMIZATIONS, None, f"使用內附整合清單｜{u.process_error(exc)}")


def previous_customizations(identity: str | None) -> Path:
    if identity is None:
        return u.CUSTOMIZATIONS
    # Do not silently substitute another baseline; that could discard a user's edits.
    return _cached(identity).customizations


def app_order(version: str):
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise u.SkipUpdate("更新器版號無效")
    return tuple(map(int, version.split(".")))


def check_app():
    data = release()
    version = data["tag_name"].removeprefix("v")
    if app_order(version) <= app_order(APP_VERSION):
        return None
    item = asset(data, "XiaoHeiForeverUpdater.exe")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", item.get("digest") or ""):
        raise u.SkipUpdate("新版程式缺少GitHub雜湊驗證")
    return {"version": version, "asset": item}


def download_app(update) -> Path:
    item = update["asset"]
    # Revalidate the fixed repository prefix, including when called outside the UI.
    expected = f"https://github.com/{REPOSITORY}/releases/download/v{update['version']}/XiaoHeiForeverUpdater.exe"
    app_order(update["version"])
    if item.get("browser_download_url") != expected or not re.fullmatch(r"sha256:[0-9a-f]{64}", item.get("digest") or ""):
        raise u.SkipUpdate("新版程式來源無效")
    raw = download(item, 150 * 1024**2)
    if not raw.startswith(b"MZ"):
        raise u.SkipUpdate("新版程式不是Windows執行檔")
    folder = u.APP / ".updates"
    folder.mkdir(exist_ok=True)
    path = folder / f"updater-{update['version']}-{uuid.uuid4().hex}.exe"
    path.write_bytes(raw)
    return path
