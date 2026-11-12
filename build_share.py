"""Build the portable package's addon-only customizations from this checkout."""
from pathlib import Path
import json
import tempfile
import uuid
import zipfile

import updater as u


def build_customizations(addons: Path = u.ADDONS, baselines: Path = u.BASELINES,
                         output: Path = u.APP / "customizations"):
    output = output.absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.prepare-customizations-', dir=output.parent) as tmp:
        ready = Path(tmp) / 'ready'
        _write_customizations(addons, baselines, ready)
        previous = None
        if output.exists():
            u.assert_plain(output)
            if not output.is_dir():
                raise u.SkipUpdate('整合輸出位置不是資料夾')
            # Keep the previous complete build outside the published bundle.
            backups = output.parent / '.customization-build-backups'
            backups.mkdir(exist_ok=True)
            u.assert_plain(backups)
            previous = backups / uuid.uuid4().hex
            if output.resolve().parent != output.parent.resolve() or previous.resolve().parent != backups.resolve():
                raise u.SkipUpdate('整合輸出備份位置不在預期資料夾')
            output.rename(previous)
        try:
            ready.rename(output)
        except Exception:
            if previous is not None:
                previous.rename(output)
            raise


def _write_customizations(addons: Path, baselines: Path, output: Path):
    output.mkdir(exist_ok=True)
    manifest = {}
    for pkg in u.PACKAGES:
        version = u.installed_version(addons, pkg)
        folders = tuple(n for n in pkg.managed_folders if (addons / n).is_dir())
        base = u.read_zip(baselines / f"{pkg.key}-{version}.zip", folders)
        live = u.read_live(addons, folders)
        changed = {key for key in base.keys() | live.keys() if base.get(key) != live.get(key)}
        if not changed:
            continue
        target = output / pkg.key
        target.mkdir(exist_ok=True)
        for label, files in (("base", base), ("local", live)):
            with zipfile.ZipFile(target / f"{label}.zip", "w", zipfile.ZIP_DEFLATED) as zipped:
                for key in sorted(changed):
                    if key in files:
                        relative, contents = files[key]
                        zipped.writestr(relative, contents)
        manifest[pkg.key] = {"version": version, "files": [live.get(k, base.get(k))[0] for k in sorted(changed)]}
    with zipfile.ZipFile(output / "hub.zip", "w", zipfile.ZIP_DEFLATED) as zipped:
        for relative, contents in u.read_live(addons, ("XiaoHeiAddonHub",)).values():
            zipped.writestr(relative, contents)
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Bundled {sum(len(p['files']) for p in manifest.values())} addon modifications and XiaoHeiAddonHub")


if __name__ == "__main__":
    build_customizations()
