from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath


APP = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
RESOURCES = Path(getattr(sys, "_MEIPASS", APP))
GAME = APP.parent / "World of Warcraft"
ADDONS = GAME / "_forever_" / "Interface" / "AddOns"
BACKUPS = APP.parent / "_codex-backups" / "一鍵更新"
BASELINES = APP / "baselines"
SETTINGS = APP / "settings.json"
CUSTOMIZATIONS = RESOURCES / "customizations"
MAX_ZIP = 150 * 1024**2
MAX_UNPACKED = 400 * 1024**2
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
VERSION = r"(?:[vV]?\d+(?:\.\d+){1,3}[a-z]?|[rR]\d+)"


class SkipUpdate(Exception):
    """A package could not be updated safely."""


@dataclass(frozen=True)
class Package:
    key: str
    label: str
    anchor: str
    source: str
    archive: str
    folders: tuple[str, ...] = ()

    @property
    def managed_folders(self):
        return (self.anchor, *self.folders)


PACKAGES = (
    Package("lueur", "Lueur", "Lueur", "1732324/lueur", rf"Lueur-({VERSION})\.zip"),
    Package("atlasloot", "AtlasLoot", "AtlasLootClassic", "1422985/atlasloot-forever",
            rf"AtlasLoot-Classic-Forever-({VERSION})-\d+-\d+\.zip",
            ("AtlasBIStooltips", *(f"AtlasLootClassic_{suffix}" for suffix in
             ("Collections", "Crafting", "Data", "DungeonsAndRaids", "Factions", "Options", "PvP")))),
    Package("threat", "仇恨值監控（ThreatClassic2）", "ThreatClassic2", "355497/threatclassic2",
            rf"ThreatClassic2-({VERSION})-forever\.zip"),
    Package("questiedb", "路線地點資料庫（QuestieDB）", "QuestieDB", "1696795/questiedb",
            rf"QuestieDB-({VERSION})-Forever\.zip"),
    Package("questie", "任務助手（Questie）", "Questie", "334372/questie",
            rf"Questie-({VERSION})\.zip"),
    Package("bbf", "BetterBlizzFrames", "BetterBlizzFrames", "940950/betterblizzframes",
            rf"BetterBlizzFrames-({VERSION})\.zip"),
    Package("sparkles", "任務戰利品閃光", "ForeverLootSparkles", "1729017/forever-loot-sparkles",
            rf"ForeverLootSparkles-({VERSION})-forever\.zip"),
    Package("shortest", "最短路線", "ShortestPathForever", "1708599/shortest-path-forever",
            rf"ShortestPathForever-({VERSION})-forever\.zip", ("ForeverCore",)),
    Package("leatrix", "Leatrix Maps", "Leatrix_Maps", "298842/leatrix-maps",
            rf"Leatrix_Maps-({VERSION})-forever\.zip"),
    Package("zone", "永恆地區資訊", "ZoneInfoForever", "1703102/zone-info-forever",
            rf"ZoneInfoForever-({VERSION})\.zip"),
    Package("drawer", "小地圖按鈕收納", "MinimapButtonDrawer", "1744034/minimap-button-drawer",
            rf"MinimapButtonDrawer-?({VERSION})\.zip"),
    Package("training", "技能學習清單（永恆分支）", "WhatsTraining", "1701676/project-1701676",
            rf"WhatsTraining-({VERSION})\.zip"),
    Package("dbm", "DBM 核心", "DBM-Core", "DeadlyBossMods/DeadlyBossMods", rf"DBM-Core-({VERSION})\.zip",
            ("DBM-GUI", "DBM-StatusBarTimers", "DBM-VPVEM")),
    Package("dbm-party", "DBM 五人副本", "DBM-Party-Forever", "DeadlyBossMods/DBM-Dungeons",
            rf"DBM-Dungeons-({VERSION})\.zip", ("DBM-Party-Vanilla",)),
    Package("dbm-raid", "DBM 團隊及世界首領", "DBM-Raids-Vanilla", "DeadlyBossMods/DBM-Vanilla",
            rf"DBM-Vanilla_SoD-({VERSION})\.zip", ("DBM-Azeroth",)),
)


def client_patch(game: Path = GAME) -> tuple[str, str]:
    lines = (game / ".build.info").read_text(encoding="utf-8-sig").splitlines()
    headers = [name.split("!", 1)[0] for name in lines[0].split("|")]
    for row in lines[1:]:
        values = dict(zip(headers, row.split("|")))
        if values.get("Product") == "wowf" and values.get("Active") == "1":
            parts = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)\.\d+", values.get("Version", ""))
            if parts:
                major, minor, patch = map(int, parts.groups())
                return ".".join(parts.groups()), str(major * 10000 + minor * 100 + patch)
    raise SkipUpdate("找不到《永恆》的有效客戶端版本。")


def resolve_game(selected: Path) -> Path:
    """Accept the game root, _forever_, Interface or AddOns, never a retail client."""
    selected = selected.expanduser().absolute()
    candidates = [selected, *list(selected.parents)[:3]]
    for game in candidates:
        if selected not in (game, game / "_forever_", game / "_forever_/Interface",
                            game / "_forever_/Interface/AddOns"):
            continue
        if not (game / ".build.info").is_file() or not (game / "_forever_/Wow.exe").is_file():
            continue
        for part in [game, *game.parents]:
            assert_plain(part)
        assert_plain(game / ".build.info")
        for part in (game / "_forever_", game / "_forever_/Interface", game / "_forever_/Interface/AddOns"):
            if part.exists() or part.is_symlink():
                assert_plain(part)
                if not part.is_dir():
                    raise SkipUpdate(f"預期的資料夾被其他檔案占用：{part}")
        client_patch(game)
        return game
    raise SkipUpdate("請選擇含 .build.info 與 _forever_ 的《永恆》遊戲資料夾，也可選 _forever_ 或 AddOns。")


def remembered_game(settings: Path = SETTINGS) -> Path:
    try:
        return resolve_game(Path(json.loads(settings.read_text(encoding="utf-8"))["game"]))
    except (OSError, ValueError, KeyError, TypeError, SkipUpdate):
        return GAME


def remember_game(game: Path, settings: Path = SETTINGS):
    pending = settings.with_name(f".{uuid.uuid4().hex}.tmp")
    pending.write_text(json.dumps({"game": str(game)}, ensure_ascii=False), encoding="utf-8")
    pending.replace(settings)


def backup_location(game: Path) -> Path:
    return game.parent / "_codex-backups" / "一鍵更新"


def baseline_location(game: Path) -> Path:
    if game == GAME:
        return BASELINES
    identity = hashlib.sha256(str(game).casefold().encode("utf-8")).hexdigest()[:20]
    return APP / "clients" / identity / "baselines"


def game_running() -> bool:
    tasklist = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tasklist.exe"
    proc = subprocess.run([str(tasklist), "/fo", "csv", "/nh"], capture_output=True,
                          check=True, timeout=12, creationflags=NO_WINDOW)
    rows = list(csv.reader(proc.stdout.decode("mbcs", errors="replace").splitlines()))
    if not rows or not any(len(row) >= 2 and row[1].strip().isdigit() for row in rows):
        raise SkipUpdate("無法確認遊戲是否已關閉。")
    return any(row and re.fullmatch(r"wow(?:t|b|classic(?:t)?|-64)?\.exe", row[0], re.I) for row in rows)


def version_name(value: str) -> str:
    if not re.fullmatch(VERSION, value, re.I):
        raise SkipUpdate(f"無法辨識版本 {value}")
    return value.lower().removeprefix("v")


def version_order(value: str):
    name = version_name(value)
    if name.startswith("r"):
        return (int(name[1:]),), ""
    parts = re.fullmatch(r"(\d+(?:\.\d+){1,3})([a-z]?)", name)
    return tuple(map(int, parts[1].split("."))), parts[2]


def toc_fields(data: bytes):
    return dict(re.findall(r"^##[ \t]+([^:\r\n]+):[ \t]*([^\r\n]*)", data.decode("utf-8-sig"), re.M))


def toc_names(folder: str):
    return tuple(f"{folder}{suffix}.toc" for suffix in ("_Forever", "_Camelot", ""))


def assert_plain(path: Path):
    info = path.lstat()
    if path.is_symlink() or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise SkipUpdate(f"資料夾或檔案使用連結，請手動檢查 {path.name}")


def installed_version(path: Path, pkg: Package) -> str:
    folder = path / pkg.anchor
    assert_plain(folder)
    for name in toc_names(pkg.anchor):
        file = folder / name
        if file.is_file():
            assert_plain(file)
            return version_name(toc_fields(file.read_bytes()).get("Version", ""))
    raise SkipUpdate("找不到插件版本檔。")


def trusted_url(url: str) -> bool:
    u = urllib.parse.urlsplit(url)
    return u.scheme == "https" and u.username is None and u.password is None and (
        u.netloc in {"api.cfwidget.com", "api.github.com", "github.com", "release-assets.githubusercontent.com",
                     "objects.githubusercontent.com"} or bool(re.fullmatch(r"[a-z0-9-]+\.forgecdn\.net", u.netloc)))


class VerifiedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not trusted_url(newurl):
            raise SkipUpdate("下載重新導向至未列入的來源。")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str, limit: int):
    if not trusted_url(url):
        raise SkipUpdate("下載來源不在允許清單。")
    opener = urllib.request.build_opener(VerifiedRedirect())
    req = urllib.request.Request(url, headers={"User-Agent": "ForeverAddonUpdater/1.0",
                                               "Accept": "application/json, text/html"})
    with opener.open(req, timeout=18) as response:
        content = response.read(limit + 1)
    if len(content) > limit:
        raise SkipUpdate("來源回應超過檔案大小上限。")
    return content


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    size: int
    digest: str = ""


def head_size(url: str) -> int:
    if not trusted_url(url):
        raise SkipUpdate("下載來源不在允許清單。")
    opener = urllib.request.build_opener(VerifiedRedirect())
    req = urllib.request.Request(url, method='HEAD', headers={'User-Agent':'ForeverAddonUpdater/1.0'})
    with opener.open(req, timeout=18) as response:
        size = int(response.headers.get('Content-Length', '0'))
    if not 0 < size <= MAX_ZIP:
        raise SkipUpdate("官方下載檔未提供有效大小，已保留現況。")
    return size


def github_release_data(repository: str, selector='latest', version_hint=None):
    import github_source
    return github_source.release_data(repository, selector, fetch, head_size,
                                      APP/'release-cache', version_hint)


def find_release(pkg: Package, patch: str, version: str | None = None) -> Release:
    version = version_name(version) if version is not None else None
    owner, project = pkg.source.split("/", 1)
    if owner.isdecimal():
        data = json.loads(fetch(f"https://api.cfwidget.com/{owner}", 6 * 1024**2))
        project_url = f"https://www.curseforge.com/wow/addons/{project}"
        if str(data.get("id")) != owner or data.get("urls", {}).get("curseforge") != project_url:
            raise SkipUpdate("來源的專案資料有變動，需手動核對。")
        releases = []
        for file in data.get("files", []):
            name = file.get("name", "")
            match = re.fullmatch(pkg.archive, name, re.I)
            ident = file.get("id")
            if not (match and (version is None or version_name(match[1]) == version)
                    and type(ident) is int and ident > 0 and file.get("type") == "release"
                    and patch in file.get("versions", []) and file.get("url") == f"{project_url}/files/{ident}"):
                continue
            url = f"https://edge.forgecdn.net/files/{ident // 1000}/{ident % 1000:03d}/{urllib.parse.quote(name)}"
            releases.append((ident, Release(version_name(match[1]), url, int(file["filesize"]))))
        if releases:
            return max(releases, key=lambda item: item[0])[1]
    else:
        # A portable copy may be taking over an existing, older installation.
        # Recover its exact original from author releases instead of guessing
        # that the installed (possibly translated) files are pristine.
        for page in range(1, 6) if version is not None else (1,):
            selector = f"?per_page=100&page={page}" if version is not None else "latest"
            data = github_release_data(pkg.source, selector, version)
            releases = data if version is not None else [data]
            if not isinstance(releases, list):
                raise SkipUpdate("作者發行清單格式無效。")
            if not releases:
                break
            for release in releases:
                if release.get("draft") or release.get("prerelease"):
                    continue
                for asset in release.get("assets", []):
                    match = re.fullmatch(pkg.archive, asset.get("name", ""), re.I)
                    url = asset.get("browser_download_url", "")
                    if (match and (version is None or version_name(match[1]) == version)
                            and url.startswith(f"https://github.com/{pkg.source}/releases/download/")):
                        return Release(version_name(match[1]), url, int(asset["size"]), asset.get("digest") or "")
    wanted = f"、插件版本 {version}" if version is not None else ""
    raise SkipUpdate(f"找不到適用於《永恆》{patch}{wanted} 的作者正式發行檔。")


def recover_baseline(pkg: Package, version: str, patch: str, interface: str,
                     folders: tuple[str, ...], baselines: Path):
    """Retrieve and validate an exact author original; never derive it from live files."""
    version = version_name(version)
    destination = baselines / f"{pkg.key}-{version}.zip"
    if destination.is_file():
        assert_plain(destination)
        return
    try:
        release = find_release(pkg, patch, version)
        if release.version != version or not 0 < release.size <= MAX_ZIP:
            raise SkipUpdate("舊版原版檔的版本或大小無效。")
        raw = fetch(release.url, MAX_ZIP)
        if (len(raw) != release.size
                or (release.digest and release.digest != "sha256:" + hashlib.sha256(raw).hexdigest())):
            raise SkipUpdate("舊版原版檔完整性驗證失敗。")
        with tempfile.TemporaryDirectory(prefix="舊版比對-", dir=baselines) as tmp:
            archive = Path(tmp) / "original.zip"
            archive.write_bytes(raw)
            original = read_zip(archive, folders)
            validate_package(original, pkg, folders, interface, version)
            if destination.exists():
                raise SkipUpdate("比對檔在準備期間有變動。")
            archive.rename(destination)
    except Exception as exc:
        raise SkipUpdate(f"無法補取 {version} 舊版原版比對檔，已保留插件；{process_error(exc)}") from exc


def read_zip(archive: Path, folders: tuple[str, ...]):
    allowed = {n.casefold(): n for n in folders}
    files = {}
    total = 0
    with zipfile.ZipFile(archive) as zipped:
        for item in zipped.infolist():
            raw = item.filename.replace("\\", "/")
            parts = raw.rstrip("/").split("/")
            if (not parts or any(not p or p in {".", ".."} or p[-1] in " ." or re.search(r'[<>:"|?*\x00-\x1f]', p)
                               or re.fullmatch(r"(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", p.split(".")[0]) for p in parts)
                    or stat.S_ISLNK(item.external_attr >> 16)):
                raise SkipUpdate("ZIP 含有不安全的檔案路徑。")
            if raw.endswith("/") or parts[0].casefold() not in allowed:
                continue
            if len(parts) < 2:
                raise SkipUpdate("ZIP 的插件目錄結構無效。")
            parts[0] = allowed[parts[0].casefold()]
            relative = "/".join(parts)
            key = relative.casefold()
            total += item.file_size
            if key in files or total > MAX_UNPACKED or len(files) >= 12000:
                raise SkipUpdate("ZIP 含有重複路徑或超出解壓上限。")
            files[key] = (relative, zipped.read(item))
    return files


def read_live(addons: Path, folders: tuple[str, ...]):
    files = {}
    total = 0
    for name in folders:
        root = addons / name
        assert_plain(root)
        for dirpath, dirs, names in os.walk(root, followlinks=False):
            parent = Path(dirpath)
            for child in dirs + names:
                assert_plain(parent / child)
            for filename in names:
                file = parent / filename
                relative = file.relative_to(addons).as_posix()
                total += file.stat().st_size
                if total > MAX_UNPACKED:
                    raise SkipUpdate("現有插件檔案超過處理上限。")
                files[relative.casefold()] = (relative, file.read_bytes())
    return files


def validate_package(files, pkg: Package, folders: tuple[str, ...], interface: str, version: str):
    for folder in folders:
        toc = next((files.get(f"{folder}/{name}".casefold()) for name in toc_names(folder)
                    if f"{folder}/{name}".casefold() in files), None)
        if toc is None:
            raise SkipUpdate(f"套件缺少已安裝的模組 {folder}")
        fields = toc_fields(toc[1])
        if interface not in re.findall(r"\d+", fields.get("Interface", "")):
            raise SkipUpdate(f"{folder} 的 TOC 未標示目前《永恆》介面版本 {interface}。")
        if folder == pkg.anchor and version_name(fields.get("Version", "")) != version:
            raise SkipUpdate("ZIP 內版本與發布版本不一致。")
        for line in toc[1].decode("utf-8-sig").splitlines():
            filename = line.strip().split(" [", 1)[0].replace("\\", "/")
            if not filename.startswith("#") and filename.lower().endswith((".lua", ".xml")):
                if f"{folder}/{filename}".casefold() not in files:
                    raise SkipUpdate(f"{folder} 缺少 TOC 載入檔 {filename}")


def normalized_text(data: bytes) -> str:
    # Some existing localized files have CRCRLF from repeated Windows writes.
    # Treat that as one line break; keep real blank CRLF/CRLF lines separate.
    return re.sub(r"\r+\n", "\n", data.decode("utf-8-sig")).replace("\r", "\n")


def merge_text(base: bytes, local: bytes, fresh: bytes, temp: Path, relative: str) -> bytes:
    git = shutil.which("git")
    if not git:
        return merge_text_python(base, local, fresh, relative)
    if PurePosixPath(relative).suffix.lower() not in {".lua", ".toc", ".xml", ".md", ".txt", ".json"}:
        raise SkipUpdate(f"本機和新版都修改了 {relative}")
    paths = [temp / name for name in ("local.txt", "base.txt", "new.txt")]
    for path, contents in zip(paths, (local, base, fresh)):
        path.write_bytes(normalized_text(contents).encode("utf-8"))
    result = subprocess.run([git, "merge-file", "-p", "--", *map(str, paths)], capture_output=True,
                            timeout=15, creationflags=NO_WINDOW)
    if result.returncode == 1:
        # Git also conflicts on adjacent, non-overlapping line edits. The built-in
        # merger can resolve only provably separate edits; overlaps still stop.
        return merge_text_python(base, local, fresh, relative)
    if result.returncode:
        raise SkipUpdate(f"本機修改與新版有衝突 {relative}")
    bom = b"\xef\xbb\xbf" if fresh.startswith(b"\xef\xbb\xbf") else b""
    return bom + (result.stdout.replace(b"\n", b"\r\n") if b"\r\n" in fresh else result.stdout)


def merge_text_python(base: bytes, local: bytes, fresh: bytes, relative: str) -> bytes:
    """Conservative three-way fallback for friends' computers without Git."""
    if PurePosixPath(relative).suffix.lower() not in {".lua", ".toc", ".xml", ".md", ".txt", ".json"}:
        raise SkipUpdate(f"本機和新版都修改了 {relative}")
    original, ours, theirs = (normalized_text(b).splitlines(keepends=True)
                              for b in (base, local, fresh))
    def changes(lines):
        return [(i, j, lines[a:b]) for kind, i, j, a, b in
                difflib.SequenceMatcher(None, original, lines, autojunk=False).get_opcodes() if kind != "equal"]
    local_edits, new_edits = changes(ours), changes(theirs)
    edits = list(local_edits)
    for right in new_edits:
        if right in edits:
            continue
        a, b, _ = right
        for c, d, _ in local_edits:
            overlap = max(a, c) < min(b, d)
            # Boundary insertions are ordered before/after the replaced span.
            # Competing insertions or an insertion inside another edit conflict.
            insertion = ((a == b and c == d and a == c) or
                         (a == b and c < a < d) or (c == d and a < c < b))
            if overlap or insertion:
                raise SkipUpdate(f"本機修改與新版有衝突 {relative}")
        edits.append(right)
    result = list(original)
    for i, j, replacement in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        result[i:j] = replacement
    output = "".join(result)
    if b"\r\n" in fresh:
        output = output.replace("\n", "\r\n")
    return (b"\xef\xbb\xbf" if fresh.startswith(b"\xef\xbb\xbf") else b"") + output.encode("utf-8")


def customize_package(pkg: Package, upstream, temp: Path, folders: tuple[str, ...], customizations: Path | None = None):
    customizations = customizations if customizations is not None else CUSTOMIZATIONS
    base_zip = customizations / pkg.key / "base.zip"
    local_zip = customizations / pkg.key / "local.zip"
    if not base_zip.is_file() or not local_zip.is_file():
        return upstream
    base = read_zip(base_zip, folders)
    local = read_zip(local_zip, folders)
    relevant = {k: v for k, v in upstream.items() if k in base or k in local}
    merged, _ = merge_files(base, local, relevant, temp)
    result = dict(upstream)
    for key in base.keys() | local.keys():
        result.pop(key, None)
    result.update(merged)
    return result


def validate_dependencies(files, addons: Path, folders: tuple[str, ...]):
    available = {n.casefold() for n in folders}
    for folder in folders:
        toc = next((files[f"{folder}/{name}".casefold()][1] for name in toc_names(folder)
                    if f"{folder}/{name}".casefold() in files), None)
        if toc is None:
            raise SkipUpdate(f"套件缺少模組 {folder}")
        fields = toc_fields(toc)
        for name in ("Dependencies", "RequiredDeps"):
            for dep in re.split(r"[,\s]+", fields.get(name, "").strip()):
                if not dep or dep.startswith("Blizzard_") or dep.casefold() in available:
                    continue
                if not (addons / dep).is_dir() or not any((addons / dep / t).is_file() for t in toc_names(dep)):
                    raise SkipUpdate(f"{folder} 需要先安裝 {dep}")


def merge_files(base, current, fresh, temp: Path):
    merged = {}
    preserved = 0
    for key in sorted(base.keys() | current.keys() | fresh.keys()):
        old = base.get(key)
        local = current.get(key)
        new = fresh.get(key)
        old_data, local_data, new_data = (item[1] if item else None for item in (old, local, new))
        if local_data == old_data or local_data == new_data:
            chosen = new
        elif new_data == old_data:
            chosen = (new[0], local[1]) if local and new else local
            preserved += 1
        elif all(item is not None for item in (old, local, new)):
            chosen = new[0], merge_text(old_data, local_data, new_data, temp, new[0])
            preserved += 1
        else:
            raise SkipUpdate(f"新增或移除的檔案與本機修改衝突 {(local or new or old)[0]}")
        if chosen is not None:
            merged[key] = chosen
    return merged, preserved


def install_package(pkg: Package, release: Release, addons: Path, folders: tuple[str, ...],
                    current_version: str | None, interface: str, backups: Path, baselines: Path, running,
                    customizations: Path | None = None, previous_customizations: Path | None = None):
    existing = tuple(name for name in folders if (addons / name).exists())
    if not current_version and existing:
        raise SkipUpdate("主插件缺少但仍有其他模組，請先手動確認，避免覆蓋現有檔案。")
    old_zip = baselines / f"{pkg.key}-{current_version}.zip" if current_version else None
    if old_zip and not old_zip.is_file() and current_version != release.version:
        raise SkipUpdate(f"缺少 {current_version} 舊版原版比對檔，已保留插件，請重新執行更新以補取。")
    if not 0 < release.size <= MAX_ZIP:
        raise SkipUpdate("下載大小超過上限或無效。")
    raw = fetch(release.url, MAX_ZIP)
    if len(raw) != release.size or (release.digest and release.digest != "sha256:" + hashlib.sha256(raw).hexdigest()):
        raise SkipUpdate("下載檔完整性檢查失敗。")

    backups.mkdir(parents=True, exist_ok=True)
    assert_plain(backups)
    if backups.resolve().drive != addons.resolve().drive:
        raise SkipUpdate("備份和插件目錄必須位於同一個磁碟。")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    with tempfile.TemporaryDirectory(prefix="準備-", dir=backups) as tmp:
        work = Path(tmp)
        archive = work / "release.zip"
        archive.write_bytes(raw)
        upstream = read_zip(archive, folders)
        validate_package(upstream, pkg, folders, interface, release.version)
        validate_dependencies(upstream, addons, folders)
        live = read_live(addons, existing)
        if current_version:
            if old_zip.is_file():
                assert_plain(old_zip)
            original = read_zip(old_zip if old_zip.is_file() else archive, existing)
            root_toc = next((original.get(f"{pkg.anchor}/{name}".casefold()) for name in toc_names(pkg.anchor)
                             if f"{pkg.anchor}/{name}".casefold() in original), None)
            if not root_toc or version_name(toc_fields(root_toc[1]).get("Version", "")) != current_version:
                raise SkipUpdate("原版 ZIP 與現有版本不相符。")
            if customizations is not None:
                previous = customize_package(pkg, original, work, existing, previous_customizations)
                desired = customize_package(pkg, upstream, work, folders, customizations)
                merged, count = merge_files(previous, live, desired, work)
            else:
                merged, count = merge_files(original, live, upstream, work)
        else:
            merged, count = customize_package(pkg, upstream, work, folders, customizations), 0
        validate_package(merged, pkg, folders, interface, release.version)
        prepared = work / "new"
        for relative, content in merged.values():
            out = prepared / relative
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(content)
        if read_live(prepared, folders) != merged:
            raise SkipUpdate("更新暫存檔與預期內容不符。")
        new_zip = baselines / f"{pkg.key}-{release.version}.zip"
        if new_zip.exists():
            assert_plain(new_zip)
            if new_zip.read_bytes() != raw:
                raise SkipUpdate("原作者重發了同版號檔案，請手動核對。")
        if (running() or read_live(addons, existing) != live
                or tuple(name for name in folders if (addons / name).exists()) != existing):
            raise SkipUpdate("遊戲已開啟或插件目錄在更新期間有變動。")
        if not new_zip.exists():
            # Keep the pristine archive for the next three-way comparison.
            pending_zip = new_zip.with_name(f".{uuid.uuid4().hex}.tmp")
            pending_zip.write_bytes(raw)
            pending_zip.rename(new_zip)

        backup = backups / f"{stamp}-{pkg.key}-{current_version}-{uuid.uuid4().hex[:6]}" if existing else None
        if backup:
            backup.mkdir()
        moved = []
        installed = []
        try:
            for name in folders:
                if (addons / name).resolve().parent != addons.resolve():
                    raise SkipUpdate("插件目錄不在預期路徑。")
                if name in existing:
                    (addons / name).rename(backup / name)
                    moved.append(name)
                (prepared / name).rename(addons / name)
                installed.append(name)
            if read_live(addons, folders) != merged:
                raise SkipUpdate("安裝後檔案驗證失敗。")
        except Exception:
            for name in reversed(installed):
                (addons / name).rename(prepared / name)
            for name in reversed(moved):
                (backup / name).rename(addons / name)
            raise
    return backup, count


def process_error(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        import github_source
        if github_source.quota_error(exc):
            return "GitHub 查詢暫時達到額度上限，已保留插件；請稍後再試。"
        return f"來源目前無法讀取（HTTP {exc.code}）"
    return str(exc)


def recycle_completed_file(path: Path, parent: Path, directory: bool):
    """Recycle only a direct child of the intended updater-owned directory."""
    path = path.absolute()
    parent = parent.resolve(strict=True)
    if path.parent.resolve(strict=True) != parent or path.resolve(strict=True).parent != parent:
        raise OSError("待清理檔案不在預期的資料夾內")
    assert_plain(path)
    if path.is_dir() != directory or (not directory and not path.is_file()):
        raise OSError("待清理檔案類型不符")
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    script = r'''
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName Microsoft.VisualBasic
$path = $env:XIAOHEI_RECYCLE_PATH
if ($env:XIAOHEI_RECYCLE_KIND -eq 'directory') {
  [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory($path, [Microsoft.VisualBasic.FileIO.UIOption]::OnlyErrorDialogs, [Microsoft.VisualBasic.FileIO.RecycleOption]::SendToRecycleBin)
} else {
  [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($path, [Microsoft.VisualBasic.FileIO.UIOption]::OnlyErrorDialogs, [Microsoft.VisualBasic.FileIO.RecycleOption]::SendToRecycleBin)
}
'''
    env = dict(os.environ, XIAOHEI_RECYCLE_PATH=str(path),
               XIAOHEI_RECYCLE_KIND="directory" if directory else "file")
    result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
                            env=env, capture_output=True, timeout=45, creationflags=NO_WINDOW)
    if result.returncode or path.exists():
        raise OSError("無法送至資源回收筒")


@contextmanager
def update_lock(baselines: Path):
    import msvcrt

    with (baselines / ".update.lock").open("a+b") as lock:
        lock.seek(0, os.SEEK_END)
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise SkipUpdate("另一個更新器視窗正在更新。") from exc
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def run_updates(apply: bool, report, addons: Path | None = None, game: Path = GAME,
                backups: Path | None = None, baselines: Path | None = None, running=game_running, catalog=None):
    game = resolve_game(game)
    target = game / "_forever_/Interface/AddOns"
    if addons is not None and addons.absolute() != target:
        raise SkipUpdate("插件位置與選定的《永恆》遊戲資料夾不符。")
    addons = target
    backups = backups if backups is not None else backup_location(game)
    baselines = baselines if baselines is not None else baseline_location(game)
    patch, interface = client_patch(game)
    if apply and running():
        raise SkipUpdate("請完全關閉《魔獸世界》後，再按一次「一鍵更新」。")
    if apply:
        addons.mkdir(parents=True, exist_ok=True)
        baselines.mkdir(parents=True, exist_ok=True)
        assert_plain(baselines)
    # Also lock the selected client, even when two portable copies are running.
    with (update_lock(addons.parent) if apply else nullcontext()), (update_lock(baselines) if apply else nullcontext()):
        return update_packages(apply, report, addons, backups, baselines, running, patch, interface, catalog)


def update_packages(apply, report, addons, backups, baselines, running, patch, interface, catalog=None):
    planned = catalog.packages if catalog is not None else PACKAGES
    state_file = baselines / ".catalog-state.json"
    if state_file.is_file():
        state = json.loads(state_file.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise SkipUpdate("整合版本紀錄損壞，請手動檢查")
    else:
        state = {}
    def record(key):
        if catalog is not None and catalog.identity is not None:
            state[key] = catalog.identity
            pending = state_file.with_name(f".{uuid.uuid4().hex}.tmp")
            pending.write_text(json.dumps(state), encoding="utf-8")
            pending.replace(state_file)
    def previous(key):
        from online import previous_customizations
        return previous_customizations(state.get(key))
    tracked = {folder for p in planned for folder in p.managed_folders} | {"XiaoHeiAddonHub"}
    for folder in sorted(addons.iterdir() if addons.is_dir() else [], key=lambda path: path.name.casefold()):
        if folder.is_dir() and folder.name not in tracked:
            note = "本機自製插件" if folder.name == "XiaoHeiAddonHub" else "未設定可信更新來源"
            report(folder.name, "—", "—", f"略過｜{note}")

    updated = available = skipped = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        releases = {pkg.key: pool.submit(find_release, pkg, patch) for pkg in planned}
        for pkg in planned:
            current = latest = "—"
            try:
                exists = (addons / pkg.anchor).exists()
                current = installed_version(addons, pkg) if exists else None
                release = releases[pkg.key].result()
                latest = release.version
                missing = any(not (addons / name).is_dir() for name in pkg.managed_folders)
                no_baseline = not (baselines / f"{pkg.key}-{current}.zip").is_file()
                new_catalog = catalog is not None and catalog.identity is not None and state.get(pkg.key) != catalog.identity
                if current and (version_order(latest) < version_order(current)
                                or (latest == current and not missing and not no_baseline and not new_catalog)):
                    report(pkg.label, current, latest, "已是最新" if latest == current else "保留較新本機版本")
                    continue
                available += 1
                if not apply:
                    note = "可安裝" if not current else "可同步整合／補齊模組" if latest == current else "可更新"
                    if current and no_baseline and current != latest:
                        note += f"｜更新時會先補取 {current} 舊版原版比對檔"
                    report(pkg.label, current or "未安裝", latest,
                           note)
                    continue
                folders = pkg.managed_folders
                if current and no_baseline and current != latest:
                    existing = tuple(name for name in folders if (addons / name).is_dir())
                    recover_baseline(pkg, current, patch, interface, existing, baselines)
                backup, count = install_package(pkg, release, addons, folders, current, interface, backups, baselines, running,
                                                catalog.customizations if catalog is not None else None,
                                                previous(pkg.key) if catalog is not None and current else None)
                record(pkg.key)
                updated += 1
                retained = []
                cleanup = [(backup, backups, True)] if backup else []
                if current and current != latest:
                    cleanup.append((baselines / f"{pkg.key}-{current}.zip", baselines, False))
                for path, parent, is_directory in cleanup:
                    try:
                        recycle_completed_file(path, parent, is_directory)
                    except Exception:
                        retained.append(str(path))
                if retained:
                    skipped += 1
                    result = f"已安裝／更新｜保留 {count} 個本機異動；無法回收，保留：{'、'.join(retained)}"
                else:
                    result = ("已安裝｜包含整合繁中" if not current else
                              f"已更新／補齊｜保留 {count} 個本機異動；舊版已移至資源回收筒")
                report(pkg.label, current or "未安裝", latest, result)
            except Exception as exc:
                skipped += 1
                report(pkg.label, current or "未安裝", latest, f"保留現況｜{process_error(exc)}")
    hub = addons / "XiaoHeiAddonHub"
    hub_changed = catalog is not None and catalog.identity is not None and state.get("hub") != catalog.identity
    if hub.exists() and not hub_changed:
        report("小黑插件總入口", "已安裝", "內附版本", "保留現有總入口")
    else:
        available += 1
        try:
            if apply:
                backup = install_hub(addons, interface, running,
                                     catalog.customizations if catalog is not None else None,
                                     previous("hub") if catalog is not None and hub.exists() else None, backups)
                record("hub")
                updated += 1
                if backup:
                    try:
                        recycle_completed_file(backup, backups, True)
                    except Exception:
                        skipped += 1
                        report("小黑插件總入口", "已安裝", "整合版本", f"已更新；舊版保留於 {backup}")
                        return updated, available, skipped
            report("小黑插件總入口", "已安裝" if hub_changed else "未安裝", "整合版本", "已同步" if apply else "可安裝／同步")
        except Exception as exc:
            skipped += 1
            report("小黑插件總入口", "未安裝", "內附版本", f"未安裝｜{process_error(exc)}")
    return updated, available, skipped


def install_hub(addons: Path, interface: str, running, customizations: Path | None = None,
                previous_customizations: Path | None = None, backups: Path | None = None):
    pkg = Package("hub", "小黑插件總入口", "XiaoHeiAddonHub", "", "")
    archive = (customizations if customizations is not None else CUSTOMIZATIONS) / "hub.zip"
    files = read_zip(archive, pkg.managed_folders)
    existing = (addons / pkg.anchor).exists()
    live = read_live(addons, pkg.managed_folders) if existing else {}
    toc = files.get("xiaoheiaddonhub/xiaoheiaddonhub.toc")
    if not toc:
        raise SkipUpdate("缺少內附的插件總入口")
    version = toc_fields(toc[1]).get("Version", "")
    validate_package(files, pkg, pkg.managed_folders, interface, version)
    with tempfile.TemporaryDirectory(prefix="總入口-", dir=addons.parent) as tmp:
        staged = Path(tmp)
        if existing:
            previous_zip = (previous_customizations if previous_customizations is not None else CUSTOMIZATIONS) / "hub.zip"
            previous = read_zip(previous_zip, pkg.managed_folders)
            files, _ = merge_files(previous, live, files, staged)
            validate_package(files, pkg, pkg.managed_folders, interface, version)
        for relative, contents in files.values():
            out = staged / relative
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(contents)
        if read_live(staged, pkg.managed_folders) != files:
            raise SkipUpdate("總入口暫存驗證失敗")
        if (running() or (addons / pkg.anchor).exists() != existing
                or (existing and read_live(addons, pkg.managed_folders) != live)):
            raise SkipUpdate("遊戲已開啟或總入口在更新期間變動")
        backup = None
        if existing:
            backups.mkdir(parents=True, exist_ok=True)
            backup = backups / f"hub-{uuid.uuid4().hex}"
            backup.mkdir()
            (addons / pkg.anchor).rename(backup / pkg.anchor)
        try:
            (staged / pkg.anchor).rename(addons / pkg.anchor)
            if read_live(addons, pkg.managed_folders) != files:
                (addons / pkg.anchor).rename(staged / pkg.anchor)
                raise SkipUpdate("總入口安裝後驗證失敗")
        except Exception:
            if backup:
                (backup / pkg.anchor).rename(addons / pkg.anchor)
            raise
        return backup


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="僅檢查版本")
    parser.add_argument("--game", type=Path, default=None, help="《永恆》遊戲位置")
    args = parser.parse_args()
    if args.check:
        print(run_updates(False, lambda *row: print(" | ".join(row), flush=True), game=args.game or remembered_game()))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
