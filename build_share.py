"""Build the portable package's addon-only customizations from this checkout."""
from pathlib import Path
import json
import zipfile

import updater as u


def build_customizations(addons: Path = u.ADDONS, baselines: Path = u.BASELINES,
                         output: Path = u.APP / "customizations"):
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
