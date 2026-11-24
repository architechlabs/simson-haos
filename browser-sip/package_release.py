"""Package the browser SIP integration for Home Assistant manual installation."""

import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent
COMPONENT = ROOT / "custom_components" / "simson_v2"


def main():
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    version = manifest["version"]
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    if version != package["version"]:
        raise ValueError("The Home Assistant and npm package versions must match")

    dist = ROOT.parent / "dist"
    dist.mkdir(exist_ok=True)
    path = dist / f"simson-v2-home-assistant-{version}.zip"
    files = (
        *COMPONENT.glob("*.py"), *COMPONENT.glob("*.json"), *COMPONENT.glob("*.yaml"),
        *COMPONENT.glob("translations/*.json"), *COMPONENT.glob("brand/*.png"),
        *COMPONENT.glob("www/*.js"), *COMPONENT.glob("www/chunks/*.js"),
        *COMPONENT.glob("www/brand/*.png"), COMPONENT / "www" / "SIPJS-LICENSE.txt",
        *ROOT.glob("example-*.yaml"), *ROOT.glob("contracts/*.yaml"),
        ROOT / "INSTALL.md", ROOT / "BROWSER-SIP.md",
    )
    required = (
        COMPONENT / "brand" / "icon.png", COMPONENT / "brand" / "logo.png",
        COMPONENT / "www" / "simson-call-card.js", COMPONENT / "www" / "chunks" / "browser-phone.js",
        COMPONENT / "www" / "chunks" / "card-editor.js",
    )
    if not all(asset in files for asset in required):
        raise FileNotFoundError("Build the card and supply the Simson brand assets before packaging")
    with ZipFile(path, "w", ZIP_DEFLATED, compresslevel=9) as archive:
        for file in sorted(files):
            archive.write(file, file.relative_to(ROOT).as_posix())
    print(path)


if __name__ == "__main__":
    main()
