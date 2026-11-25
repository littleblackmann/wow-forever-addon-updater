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
from typing import Callable


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
VERSION = r"(?:[vV]?\d+(?:\.\d+){0,3}(?:[ -]?[a-z])?|[rR]\d+)"
UNMANAGED_ADDON_STATUS = "未納入整合｜已保留"


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


DUNGEON_JOURNAL = Package("dungeonjournal", "副本手冊（DungeonJournal）", "ForeverDungeonJournal",
                          "1707971/dungeonjournal", rf"(?:Forever)?DungeonJournal-?({VERSION})\.zip")
ATLASLOOT_FOREVER = Package("atlasloot", "AtlasLoot Forever", "AtlasLootClassic", "1422985/atlasloot-forever",
                            rf"AtlasLoot-Classic-Forever-({VERSION})-\d+-\d+\.zip",
                            ("AtlasBIStooltips", *(f"AtlasLootClassic_{suffix}" for suffix in
                             ("Collections", "Crafting", "Data", "DungeonsAndRaids", "Factions", "Options", "PvP"))))


PACKAGES = (
    Package("platynator", "怪物名條（Platynator）", "Platynator", "1361299/platynator", rf"Platynator-({VERSION})\.zip"),
    Package("rarescanner", "稀有與寶箱提醒（RareScanner）", "RareScanner", "84208/rarescanner", rf"RareScanner_FOREVER_({VERSION})\.zip"),
    Package("gathermate", "採集地點紀錄（GatherMate2）", "GatherMate2", "26120/gathermate2", rf"GatherMate2-({VERSION})\.zip"),
    Package("syndicator", "背包物品資料庫（Syndicator）", "Syndicator", "988370/syndicator", rf"Syndicator-({VERSION})\.zip"),
    Package("baganator", "背包整理（Baganator）", "Baganator", "914482/baganator", rf"Baganator-({VERSION})\.zip"),
    Package("auctionator", "拍賣助手（Auctionator）", "Auctionator", "6124/auctionator", rf"Auctionator-({VERSION})\.zip"),
    Package("leatrixplus", "便利功能（Leatrix Plus）", "Leatrix_Plus", "94855/leatrix-plus", rf"Leatrix_Plus-({VERSION})-forever\.zip"),
    Package("quickchannels", "聊天頻道快捷列（QuickChannels）", "QuickChannels", "itsindolence/quickchannelswow",
            rf"QuickChannels-v?({VERSION})\.zip"),
    Package("dialogueui", "任務對話介面（Dialogue UI）", "DialogueUI", "989270/dialogueui", rf"DialogueUI-({VERSION})\.zip"),
    Package("lueur", "Lueur", "Lueur", "1732324/lueur", rf"Lueur-({VERSION})\.zip"),
    DUNGEON_JOURNAL,
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
    Package("rurutia", "露露緹婭 DBM 語音包", "DBM-VPRurutia", "1711883/dbm-voicepack-rurutia",
            rf"DBM-VPRurutia[ -]+({VERSION})\.zip"),
    Package("hunterpetinfo", "獵人寵物查詢", "ForeverHunterPetInfo", "1811105/hunterpetinfo-forever",
            rf"ForeverHunterPetInfo-({VERSION})-forever\.zip"),
    Package("levelingbis", "練等裝備推薦", "ForeverLevelingBiS", "1719370/forever-leveling-bis",
            rf"ForeverLevelingBiS-({VERSION})-forever\.zip"),
    Package("plg", "專業技能升級指南（PLG）", "ProfessionLevelingGuide", "1682685/plg-profession-leveling-guide",
            rf"ProfessionLevelingGuide-({VERSION})\.zip"),
)

FOREVER_CORE = Package("forevercore", "永恆共用元件（ForeverCore）", "ForeverCore", "1796337/forevercore",
                       rf"ForeverCore-({VERSION})-forever\.zip")


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
    return value.lower().removeprefix("v").replace(" ", "").replace("-", "")


def version_order(value: str):
    name = version_name(value)
    if name.startswith("r"):
        return (int(name[1:]),), ""
    parts = re.fullmatch(r"(\d+(?:\.\d+){0,3})([a-z]?)", name)
    return tuple(map(int, parts[1].split("."))), parts[2]


def toc_fields(data: bytes):
    return dict(re.findall(r"^##[ \t]+([^:\r\n]+):[ \t]*([^\r\n]*)", data.decode("utf-8-sig"), re.M))


def toc_names(folder: str):
    return tuple(f"{folder}{suffix}.toc" for suffix in ("_Forever", "_Camelot", ""))


def package_version(pkg: Package, toc: bytes, read_file: Callable[[str], bytes]) -> str:
    version = version_name(toc_fields(toc).get("Version", ""))
    if pkg.key == "dialogueui" and version == "1.0.7c":
        # CurseForge file 9666149 was released as 1.0.7-d but retained the c TOC.
        marker = read_file("DialogueUI/Code/Dialogue/QuestHeaderWidget.lua")
        if hashlib.sha256(marker).hexdigest() == "2f6c5a1f45e2bf763b4c9ceba695f2645a561767ec33acd3887916b6280a07bd":
            return "1.0.7d"
    return version


def archived_version(pkg: Package, toc: bytes, files) -> str:
    return package_version(pkg, toc, lambda relative: files.get(relative.casefold(), ("", b""))[1])


def assert_plain(path: Path):
    info = path.lstat()
    if path.is_symlink() or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise SkipUpdate(f"資料夾或檔案使用連結，請手動檢查 {path.name}")


def installed_toc(path: Path, name: str) -> bytes:
    folder = path / name
    assert_plain(folder)
    for toc in toc_names(name):
        file = folder / toc
        if file.is_file():
            assert_plain(file)
            return file.read_bytes()
    raise SkipUpdate("找不到插件版本檔。")


def installed_version(path: Path, pkg: Package, toc: bytes | None = None) -> str:
    def read_marker(relative):
        marker = path / relative
        if not marker.is_file():
            return b""
        assert_plain(marker)
        return marker.read_bytes()
    return package_version(pkg, installed_toc(path, pkg.anchor) if toc is None else toc, read_marker)


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
            validate_package(original, pkg, archive_folders(pkg, folders, original), interface, version)
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


def archived_toc(files, folder: str):
    return next((files[f"{folder}/{name}".casefold()][1] for name in toc_names(folder)
                 if f"{folder}/{name}".casefold() in files), None)


def bundles_forever_core(pkg: Package) -> bool:
    return pkg.key == "shortest" and pkg.anchor == "ShortestPathForever" and FOREVER_CORE.anchor in pkg.folders


def embeds_forever_core(pkg: Package, fields) -> bool:
    return bundles_forever_core(pkg) and fields.get("X-Forever-Core-Embed") == "1"


def validate_forever_core_identity(fields):
    project = fields.get("X-Curse-Project-ID", "").strip()
    if project == "1796337" or (not project and fields.get("X-Website") == "https://github.com/cjber/forever-core"):
        return
    raise SkipUpdate("無法確認此 ForeverCore 是原作者的套件，已保留現況。")


def archive_folders(pkg: Package, folders: tuple[str, ...], files) -> tuple[str, ...]:
    toc = archived_toc(files, pkg.anchor)
    if toc and embeds_forever_core(pkg, toc_fields(toc)):
        return tuple(folder for folder in folders if folder != "ForeverCore")
    return folders


def validate_package(files, pkg: Package, folders: tuple[str, ...], interface: str, version: str):
    for folder in folders:
        toc = archived_toc(files, folder)
        if toc is None:
            raise SkipUpdate(f"套件缺少已安裝的模組 {folder}")
        fields = toc_fields(toc)
        if pkg is FOREVER_CORE:
            validate_forever_core_identity(fields)
        if interface not in re.findall(r"\d+", fields.get("Interface", "")):
            raise SkipUpdate(f"{folder} 的 TOC 未標示目前《永恆》介面版本 {interface}。")
        if folder == pkg.anchor and archived_version(pkg, toc, files) != version:
            raise SkipUpdate("ZIP 內版本與發布版本不一致。")
        load_files = set()
        for line in toc.decode("utf-8-sig").splitlines():
            filename = line.strip().split(" [", 1)[0].replace("\\", "/")
            if not filename.startswith("#") and filename.lower().endswith((".lua", ".xml")):
                load_files.add(filename.casefold())
                if f"{folder}/{filename}".casefold() not in files:
                    raise SkipUpdate(f"{folder} 缺少 TOC 載入檔 {filename}")
        if folder == pkg.anchor and embeds_forever_core(pkg, fields):
            core_scripts = {f"libs/forevercore/{name}" for name in ("core/loader.lua", "begin.lua", "core.lua", "end.lua")}
            if not core_scripts <= load_files:
                raise SkipUpdate("最短路線的 TOC 缺少內嵌 ForeverCore 載入項目。")


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


def recognized_package(pkg: Package, original, live, temp: Path, folders: tuple[str, ...], customizations: Path):
    """Recognize known translated files, leaving unrelated personal files for merging."""
    base_zip, local_zip = (customizations / pkg.key / f"{label}.zip" for label in ("base", "local"))
    if not base_zip.is_file() or not local_zip.is_file():
        return None
    try:
        expected = customize_package(pkg, original, temp, folders, customizations)
    except SkipUpdate:
        # A current translation may not apply backwards to an older author file.
        # This is only recognition; the desired package is still validated later.
        return None
    touched = set(read_zip(base_zip, folders)) | set(read_zip(local_zip, folders))
    for key in touched:
        left, right = live.get(key), expected.get(key)
        if left is None or right is None:
            if left is not right:
                return None
        elif left[1] != right[1]:
            try:
                if normalized_text(left[1]) != normalized_text(right[1]):
                    return None
            except UnicodeError:
                return None
    return expected if touched else None


def previous_package(pkg: Package, original, live, temp: Path, folders: tuple[str, ...],
                     customizations: Path, previous_customizations: Path | Callable[[], Path] | None):
    """Recognize a shipped historical translation only from its exact live files.

    A fresh portable manager has no catalog state; a manually upgraded client may
    still name an older catalog. Never try to apply today's translation backwards
    to an older author database in either case. Unrecognized edits still use the
    normal conservative merge and are never overwritten by this recovery path.
    """
    recognized = recognized_package(pkg, original, live, temp, folders, customizations)
    if recognized is not None:
        return recognized
    toc = next((original.get(f"{pkg.anchor}/{name}".casefold()) for name in toc_names(pkg.anchor)
                if f"{pkg.anchor}/{name}".casefold() in original), None)
    version = archived_version(pkg, toc[1], original) if toc else ""
    archive = customizations / "history.zip"
    if version and archive.is_file():
        name = f"{pkg.key}-{version}"
        historical = read_zip(archive, (name,))
        if historical:
            root = temp / "history" / name
            target = root / pkg.key
            target.mkdir(parents=True)
            for label in ("base", "local"):
                item = historical.get(f"{name}/{label}.zip".casefold())
                if item is None:
                    raise SkipUpdate("舊版整合比對資料不完整，已保留現況。")
                (target / f"{label}.zip").write_bytes(item[1])
            expected = customize_package(pkg, original, temp, folders, root)
            touched = set(read_zip(target / "base.zip", folders)) | set(read_zip(target / "local.zip", folders))
            def same(key):
                left, right = live.get(key), expected.get(key)
                if left is None or right is None:
                    return left is right
                if left[1] == right[1]:
                    return True
                try:
                    return normalized_text(left[1]) == normalized_text(right[1])
                except UnicodeError:
                    return False
            if touched and all(same(key) for key in touched):
                return expected
    if original and all(k in live and live[k][1] == value[1] for k, value in original.items()):
        return original
    previous_root = previous_customizations() if callable(previous_customizations) else previous_customizations
    return customize_package(pkg, original, temp, folders, previous_root)


def validate_dependencies(files, addons: Path, folders: tuple[str, ...]):
    available = {n.casefold() for n in folders}
    for folder in folders:
        toc = archived_toc(files, folder)
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
        managed_folders = folders
        folders = archive_folders(pkg, managed_folders, upstream)
        if folders != managed_folders:
            # A standalone Core may still carry shared settings or be used by other addons.
            upstream = {key: entry for key, entry in upstream.items() if not key.startswith("forevercore/")}
        existing = tuple(name for name in folders if (addons / name).exists())
        if not current_version and existing:
            raise SkipUpdate("主插件缺少但仍有其他模組，請先手動確認，避免覆蓋現有檔案。")
        validate_package(upstream, pkg, folders, interface, release.version)
        validate_dependencies(upstream, addons, folders)
        live = read_live(addons, existing)
        if current_version:
            if old_zip.is_file():
                assert_plain(old_zip)
            original = read_zip(old_zip if old_zip.is_file() else archive, existing)
            root_toc = archived_toc(original, pkg.anchor)
            if not root_toc or archived_version(pkg, root_toc, original) != current_version:
                raise SkipUpdate("原版 ZIP 與現有版本不相符。")
            if customizations is not None:
                previous = previous_package(pkg, original, live, work, existing,
                                            customizations, previous_customizations)
                desired = customize_package(pkg, upstream, work, folders, customizations)
                merged, count = merge_files(previous, live, desired, work)
            else:
                merged, count = merge_files(original, live, upstream, work)
        else:
            merged, count = customize_package(pkg, upstream, work, folders, customizations), 0
        if archive_folders(pkg, managed_folders, merged) != folders:
            raise SkipUpdate("本機修改影響 ForeverCore 的載入方式，已保留現況。")
        validate_package(merged, pkg, folders, interface, release.version)
        unchanged = current_version == release.version and existing == folders and merged == live
        prepared = work / "new"
        if not unchanged:
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

        if unchanged:
            return None, count

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


def delete_replaced_file(path: Path, parent: Path, directory: bool):
    """Delete only a verified direct child of the updater-owned directory."""
    path = path.absolute()
    parent = parent.resolve(strict=True)
    assert_plain(path)
    target = path.resolve(strict=True)
    if path.parent.resolve(strict=True) != parent or target.parent != parent:
        raise OSError("待清理檔案不在預期的資料夾內")
    if target.is_dir() != directory or (not directory and not target.is_file()):
        raise OSError("待清理檔案類型不符")
    if directory:
        shutil.rmtree(target)
    else:
        target.unlink()


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


def retire_atlasloot(addons: Path, baselines: Path, backups: Path, folders: tuple[str, ...],
                     replacement: Release, interface: str, running):
    pkg = DUNGEON_JOURNAL
    baseline = baselines / f"{pkg.key}-{replacement.version}.zip"
    assert_plain(baseline)
    if (baseline.stat().st_size != replacement.size or
            (replacement.digest and replacement.digest != "sha256:" + hashlib.sha256(baseline.read_bytes()).hexdigest())):
        raise SkipUpdate("副本手冊原版檔未通過完整性檢查。")
    original = read_zip(baseline, pkg.managed_folders)
    live = read_live(addons, pkg.managed_folders)
    validate_package(original, pkg, pkg.managed_folders, interface, replacement.version)
    validate_package(live, pkg, pkg.managed_folders, interface, replacement.version)
    validate_dependencies(live, addons, pkg.managed_folders)
    if original.keys() - live.keys():
        raise SkipUpdate("副本手冊缺少檔案，已保留 AtlasLoot。")

    atlas = ATLASLOOT_FOREVER
    paths = [addons / name for name in folders]
    core = addons / atlas.anchor
    for path in paths:
        assert_plain(path)
        if path.resolve().parent != addons.resolve():
            raise SkipUpdate("AtlasLoot 模組不在預期路徑。")
        fields = toc_fields(installed_toc(addons, path.name))
        if ("AtlasLoot Forever" not in fields.get("Title", "")
                or not re.search(r"\b16\d{3}\b", fields.get("Interface", ""))
                or (path == core and fields.get("X-Curse-Project-ID") != "1422985")):
            raise SkipUpdate(f"無法辨認 {path.name} 為 AtlasLoot Forever。")

    names = {path.name.casefold() for path in paths}
    for toc in addons.glob("*/*.toc"):
        if toc.parent.name.casefold() in names:
            continue
        assert_plain(toc.parent)
        assert_plain(toc)
        fields = toc_fields(toc.read_bytes())
        dependencies = " ".join(fields.get(field, "") for field in ("Dependencies", "RequiredDeps", "Dep"))
        if names.intersection(re.split(r"[,\s]+", dependencies.casefold())):
            raise SkipUpdate(f"{toc.parent.name} 仍需要 AtlasLoot。")

    # Keep a complete, restorable copy outside AddOns, including personal files.
    # Move the core last so an interrupted migration can still identify its version.
    original_atlas = None
    if core in paths:
        paths.remove(core)
        archive = baselines / f"{atlas.key}-{installed_version(addons, atlas)}.zip"
        if archive.exists():
            assert_plain(archive)
            original_atlas = archive
        paths.append(core)
    if running():
        raise SkipUpdate("遊戲已重新開啟，已保留 AtlasLoot。")
    backups.mkdir(parents=True, exist_ok=True)
    assert_plain(backups)
    backup = backups / f"AtlasLoot-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
    backup.mkdir()
    moved = []
    try:
        if original_atlas:
            saved = backup / original_atlas.name
            shutil.copy2(original_atlas, saved)
            if saved.read_bytes() != original_atlas.read_bytes():
                raise OSError("AtlasLoot 原版 ZIP 備份驗證失敗。")
        for path in paths:
            path.rename(backup / path.name)
            moved.append(path)
        if running():
            raise OSError("遊戲已重新開啟，已還原 AtlasLoot。")
        if original_atlas:
            original_atlas.unlink()
    except OSError:
        for path in reversed(moved):
            (backup / path.name).rename(path)
        if original_atlas:
            (backup / original_atlas.name).unlink(missing_ok=True)
        backup.rmdir()
        raise


def update_packages(apply, report, addons, backups, baselines, running, patch, interface, catalog=None):
    planned = catalog.packages if catalog is not None else PACKAGES
    shortest = next((pkg for pkg in planned if bundles_forever_core(pkg)), None)
    if shortest and (addons / FOREVER_CORE.anchor).exists():
        # Process this after Shortest Path, which may switch from the old bundle to the embedded format.
        planned = (*planned, FOREVER_CORE)
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
    tracked = {folder.casefold() for p in planned for folder in p.managed_folders} | {"xiaoheiaddonhub"}
    atlas_folders = ()
    if DUNGEON_JOURNAL in planned and tracked.isdisjoint(name.casefold() for name in ATLASLOOT_FOREVER.managed_folders):
        atlas_folders = tuple(name for name in ATLASLOOT_FOREVER.managed_folders if (addons / name).exists())
        tracked.update(name.casefold() for name in atlas_folders)
    dungeon_release = None
    for folder in sorted(addons.iterdir() if addons.is_dir() else [], key=lambda path: path.name.casefold()):
        if (folder.name.casefold() not in tracked and folder.is_dir()
                and any(toc.is_file() for toc in folder.glob("*.toc"))):
            report(folder.name, "—", "—", UNMANAGED_ADDON_STATUS)

    updated = available = skipped = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        releases = {pkg.key: pool.submit(find_release, pkg, patch) for pkg in planned}
        for pkg in planned:
            current = latest = "—"
            try:
                exists = (addons / pkg.anchor).exists()
                standalone = pkg is FOREVER_CORE
                if standalone:
                    if not exists:
                        continue
                    if shortest and (addons / shortest.anchor).exists():
                        shortest_toc = installed_toc(addons, shortest.anchor)
                        if not embeds_forever_core(shortest, toc_fields(shortest_toc)):
                            continue
                toc = installed_toc(addons, pkg.anchor) if exists else None
                if standalone:
                    validate_forever_core_identity(toc_fields(toc))
                current = installed_version(addons, pkg, toc) if toc is not None else None
                release = releases[pkg.key].result()
                latest = release.version
                folders = pkg.managed_folders
                embedded = toc is not None and embeds_forever_core(pkg, toc_fields(toc))
                missing = any(not (addons / name).is_dir() for name in folders
                              if not (embedded and name == "ForeverCore"))
                no_baseline = not (baselines / f"{pkg.key}-{current}.zip").is_file()
                active_catalog = None if standalone else catalog
                new_catalog = (active_catalog is not None and active_catalog.identity is not None
                               and state.get(pkg.key) != active_catalog.identity)
                if current and (version_order(latest) < version_order(current)
                                or (latest == current and not missing and not no_baseline and not new_catalog)):
                    if atlas_folders and pkg == DUNGEON_JOURNAL and latest == current:
                        dungeon_release = release
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
                if current and no_baseline and current != latest:
                    existing = tuple(name for name in folders if (addons / name).is_dir())
                    recover_baseline(pkg, current, patch, interface, existing, baselines)
                backup, count = install_package(pkg, release, addons, folders, current, interface, backups, baselines, running,
                                                active_catalog.customizations if active_catalog is not None else None,
                                                (lambda key=pkg.key: previous(key)) if active_catalog is not None and current else None)
                if active_catalog is not None:
                    record(pkg.key)
                if atlas_folders and pkg == DUNGEON_JOURNAL:
                    dungeon_release = release
                updated += 1
                retained = []
                cleanup = [(backup, backups, True)] if backup else []
                if current and current != latest:
                    cleanup.append((baselines / f"{pkg.key}-{current}.zip", baselines, False))
                for path, parent, is_directory in cleanup:
                    try:
                        delete_replaced_file(path, parent, is_directory)
                    except Exception:
                        retained.append(str(path))
                if retained:
                    skipped += 1
                    result = f"已安裝／更新｜保留 {count} 個本機異動；舊檔未能完整刪除：{'、'.join(retained)}"
                else:
                    result = ("已是最新｜更新紀錄已同步" if current and backup is None else
                              "已安裝" if not current else
                              f"已更新／補齊｜保留 {count} 個本機異動；舊版已刪除")
                report(pkg.label, current or "未安裝", latest, result)
            except Exception as exc:
                skipped += 1
                report(pkg.label, current or "未安裝", latest, f"保留現況｜{process_error(exc)}")
    hub = addons / "XiaoHeiAddonHub"
    hub_changed = catalog is not None and catalog.identity is not None and state.get("hub") != catalog.identity
    try:
        newer_hub = hub_changed and hub.is_dir() and hub_is_newer(addons, catalog.customizations)
        if newer_hub:
            report("小黑插件總入口", newer_hub[0], newer_hub[1], "保留較新本機版本")
        elif hub.exists() and not hub_changed:
            report("小黑插件總入口", "已安裝", "內附版本", "保留現有總入口")
        else:
            available += 1
            if apply:
                backup = install_hub(addons, interface, running,
                                     catalog.customizations if catalog is not None else None,
                                     previous("hub") if catalog is not None and hub.exists() else None, backups)
                record("hub")
                updated += 1
                if backup:
                    try:
                        delete_replaced_file(backup, backups, True)
                    except Exception:
                        skipped += 1
                        report("小黑插件總入口", "已安裝", "整合版本", f"已更新｜舊檔未能完整刪除：{backup}")
                        return updated, available, skipped
            report("小黑插件總入口", "已安裝" if hub_changed else "未安裝", "整合版本", "已同步" if apply else "可安裝／同步")
    except Exception as exc:
        skipped += 1
        report("小黑插件總入口", "未安裝", "內附版本", f"未安裝｜{process_error(exc)}")
    if atlas_folders:
        available += 1
        try:
            if apply:
                if dungeon_release is None:
                    raise SkipUpdate("副本手冊尚未通過驗證。")
                retire_atlasloot(addons, baselines, backups, atlas_folders, dungeon_release, interface, running)
                updated += 1
            result = "已移出遊戲，備份在「查看保留檔案」" if apply else "副本手冊驗證後移除舊模組並保留備份"
        except Exception as exc:
            skipped += 1
            result = f"保留現況｜{process_error(exc)}"
        report(ATLASLOOT_FOREVER.label, "已安裝", "已由副本手冊取代", result)
    return updated, available, skipped


def hub_is_newer(addons: Path, customizations: Path) -> tuple[str, str] | None:
    name = "XiaoHeiAddonHub"
    try:
        current = version_name(toc_fields(installed_toc(addons, name)).get("Version", ""))
    except (OSError, UnicodeDecodeError, SkipUpdate):
        return None
    with zipfile.ZipFile(customizations / "hub.zip") as archive:
        bundled = version_name(toc_fields(archive.read(f"{name}/{name}.toc")).get("Version", ""))
    if version_order(current) > version_order(bundled):
        return current, bundled
    return None


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
            # A newly extracted manager has no per-client catalog state. Recognize
            # a known shipped hub before merging, otherwise today's bundled hub
            # would become the comparison base and silently preserve the old hub.
            live_toc = live.get("xiaoheiaddonhub/xiaoheiaddonhub.toc")
            live_version = version_name(toc_fields(live_toc[1]).get("Version", "")) if live_toc else ""
            history = (customizations if customizations is not None else CUSTOMIZATIONS) / "history.zip"
            if live_version and history.is_file():
                name = f"hub-{live_version}"
                files_in_history = read_zip(history, (name,))
                old_hub = files_in_history.get(f"{name}/hub.zip".casefold())
                if old_hub is not None:
                    candidate = staged / "previous-hub.zip"
                    candidate.write_bytes(old_hub[1])
                    known = read_zip(candidate, pkg.managed_folders)
                    def same_hub_file(key, value):
                        if key not in live:
                            return False
                        if live[key][1] == value[1]:
                            return True
                        try:
                            return normalized_text(live[key][1]) == normalized_text(value[1])
                        except UnicodeError:
                            return False
                    if known and all(same_hub_file(k, v) for k, v in known.items()):
                        previous = known
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
