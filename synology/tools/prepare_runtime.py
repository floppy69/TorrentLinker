#!/usr/bin/env python3
"""Build relocatable DSM 7.3/7.4 x86_64 SPKs outside the upstream checkout.

Runtime compatibility is checked against the DSM 7.3 x86_64 glibc ceiling.
Actual DSM operation still requires a physical NAS acceptance test.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PYTHON_RELEASE = "3.12.16+20261026"
PYTHON_ARCHIVE = "cpython-3.12.16%2B20261026-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
PYTHON_SHA256 = "ce4f6d0a6cfdb3bed6e44c2f9affd85943c76a42e25ad3a259002f31d6fb8a20"
SEVENZIP_ARCHIVE = "7z2605-linux-x64.tar.xz"
SEVENZIP_SHA256 = "22cf82fcc6eb7474f1d5bb4f02c0f8ebd573a718089d6833dc30f8350a3b232e"
PYTHON_VERSION = "3.12"
MAX_GLIBC = (2, 36)
SYSTEM_LIBS = {
    "libc.so.6", "libm.so.6", "libpthread.so.0", "libdl.so.2",
    "librt.so.1", "libutil.so.1", "libresolv.so.2",
    "ld-linux-x86-64.so.2", "linux-vdso.so.1",
}
DIRECT_PACKAGES = {
    "packaging", "qbittorrent-api", "httpx", "requests", "guessit",
    "torf", "keyring", "pillow", "numpy", "pymediainfo", "mutagen",
    "tzdata", "cryptography", "mcp", "fastapi", "uvicorn", "markdown-it-py",
}


def run(*command: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def get(url: str, digest: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "torrentlinker-synology-build"})
    with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output)
    actual = hashlib.sha256(destination.read_bytes()).hexdigest()
    if actual != digest:
        raise ValueError(f"SHA256 mismatch for {destination.name}: {actual}")


def unpack(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:*") as content:
        content.extractall(destination, filter="data")


def is_elf(file: Path) -> bool:
    if not file.is_file():
        return False
    with file.open("rb") as stream:
        return stream.read(4) == b"\x7fELF"


def elf_files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if is_elf(p))


def audit_and_bundle_native(payload: Path) -> dict[str, object]:
    """Bundle non-glibc ELF dependency closure; reject wrong ABI or newer glibc."""
    library_dir = payload / "native/lib"
    library_dir.mkdir(parents=True, exist_ok=True)
    vendor: set[str] = set()
    # lddtree reads ELF metadata without executing the target file.
    for executable in elf_files(payload):
        tree = subprocess.run(
            ["lddtree", "-l", str(executable)], check=True, capture_output=True, text=True
        )
        for text in tree.stdout.splitlines():
            name = text.strip()
            if not name or name == str(executable) or name == "linux-vdso.so.1":
                continue
            source = Path(name)
            if not source.is_absolute() or not source.is_file():
                raise ValueError(f"Unresolved ELF dependency for {executable}: {name}")
            if source.name in SYSTEM_LIBS or source.resolve().is_relative_to(payload):
                continue
            destination = library_dir / source.name
            if destination.exists():
                if destination.read_bytes() != source.read_bytes():
                    raise ValueError(f"Conflicting ELF libraries named {source.name}")
            else:
                shutil.copyfile(source, destination)
                vendor.add(source.name)

    binaries = elf_files(payload)
    for executable in binaries:
        with executable.open("rb") as stream:
            header = stream.read(20)
        if (
            len(header) < 20
            or header[:6] != b"\x7fELF\x02\x01"
            or struct.unpack_from("<H", header, 18)[0] != 62
        ):
            raise ValueError(f"Not an x86_64 little-endian ELF: {executable}")
        versions = subprocess.run(
            ["readelf", "-VW", str(executable)], check=True, capture_output=True, text=True
        ).stdout
        for major, minor in re.findall(r"GLIBC_(\d+)\.(\d+)", versions):
            if (int(major), int(minor)) > MAX_GLIBC:
                raise ValueError(
                    f"{executable} needs GLIBC_{major}.{minor}; DSM 7.3 target ceiling is 2.36"
                )
    return {
        "elf_count": len(binaries),
        "vendor_libraries": sorted(vendor),
        "system_libraries": sorted(SYSTEM_LIBS),
        "glibc_symbol_max": "2.36",
    }


def smoke(runtime: Path, payload: Path) -> None:
    from http.cookies import SimpleCookie
    from urllib.parse import quote

    import urllib.request

    site = runtime / "lib/python3.12/site-packages"
    env = dict(os.environ)
    env.update({
        "PYTHONHOME": str(runtime),
        "PYTHONPATH": str(site),
        "PYTHONNOUSERSITE": "1",
        "PATH": f"{payload / 'native/bin'}:{runtime / 'bin'}:{env.get('PATH', '')}",
        "LD_LIBRARY_PATH": f"{payload / 'native/lib'}:{runtime / 'lib'}",
    })
    python = runtime / "bin/python3.12"
    checks = (
        "import fastapi, uvicorn, httpx, requests, numpy, cryptography, mcp\n"
        "import packaging, qbittorrentapi, guessit, torf, keyring, mutagen, tzdata\n"
        "import socks, markdown_it; from PIL import Image\n"
        "from pymediainfo import MediaInfo\n"
        "assert MediaInfo.can_parse(), 'Bundled libmediainfo cannot be loaded'\n"
        "import torrentlinker.web.server\n"
        "from torrentlinker import documentation\n"
        "for lang in ('fr', 'en'):\n"
        "    for guide in documentation.guides(lang):\n"
        "        assert documentation.document_path(guide['path']).is_file()\n"
        "from torrentlinker.companion import extension_zip\n"
        "from zipfile import ZipFile\n"
        "from io import BytesIO\n"
        "import json\n"
        "with ZipFile(BytesIO(extension_zip('https://nas.example.test:8787/'))) as bundle:\n"
        "    assert bundle.testzip() is None\n"
        "    manifest = json.loads(bundle.read('torrentlinker-companion/manifest.json'))\n"
        "    assert 'https://nas.example.test/*' in manifest['host_permissions']\n"
    )
    run(str(python), "-c", checks, env=env)
    run(str(payload / "native/bin/7zz"), "i", env=env)

    # Real server smoke test, using an ephemeral password and loopback port.
    with tempfile.TemporaryDirectory(prefix="torrentlinker-smoke-") as tmp:
        root = Path(tmp)
        secret = root / "password"
        secret.write_text("ci-only-replace-this-password-strong", encoding="utf-8")
        process = subprocess.Popen(
            [
                str(python), "-m", "torrentlinker.web.server",
                "--host", "127.0.0.1", "--port", "18787",
                "--config", str(root / "config"), "--password-file", str(secret),
            ],
            env=env, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        try:
            for attempt in range(60):
                if process.poll() is not None:
                    raise RuntimeError("TorrentLinker server exited during startup")
                try:
                    with urllib.request.urlopen(
                        "http://127.0.0.1:18787/healthz", timeout=1
                    ) as response:
                        if response.status == 200:
                            base = "http://127.0.0.1:18787/"
                            login = urllib.request.Request(
                                base + "api/login",
                                data=json.dumps({
                                    "password": "ci-only-replace-this-password-strong",
                                }).encode("utf-8"),
                                headers={
                                    "Content-Type": "application/json",
                                    "X-TorrentLinker": "1",
                                },
                                method="POST",
                            )
                            with urllib.request.urlopen(login, timeout=5) as auth:
                                cookie = SimpleCookie()
                                cookie.load(auth.headers["Set-Cookie"])
                                session = "tl_session=" + cookie["tl_session"].value

                            def fetch(path: str, *, authenticated: bool = True) -> bytes:
                                req = urllib.request.Request(
                                    base + path,
                                    headers={"Cookie": session} if authenticated else {},
                                )
                                with urllib.request.urlopen(req, timeout=10) as result:
                                    if result.status != 200:
                                        raise ValueError(f"Broken Web link: {path} -> {result.status}")
                                    return result.read()

                            page = fetch("", authenticated=False).decode("utf-8")
                            links = set(re.findall(
                                r'(?:src|href)="(static/[^"#?]+)"', page,
                            ))
                            if len(links) < 15:
                                raise ValueError("The Web UI is missing bundled asset links")
                            for link in sorted(links):
                                if not fetch(link, authenticated=False):
                                    raise ValueError(f"Empty Web asset: {link}")

                            images: set[str] = set()
                            for lang in ("fr", "en"):
                                guides = json.loads(fetch(f"api/documentation?language={lang}"))
                                if len(guides) < 15:
                                    raise ValueError(f"Missing {lang} guide index")
                                for guide in guides:
                                    name = quote(guide["path"], safe="/")
                                    content = json.loads(fetch(f"api/documentation/page/{name}"))
                                    images.update(re.findall(
                                        r'src="(api/documentation/file/[^"#?]+)"',
                                        content["html"],
                                    ))
                                # Standalone guide links must also work in the browser.
                                fetch(f"documentation/{quote(guides[0]['path'], safe='/')}")
                            if len(images) < 20:
                                raise ValueError("Missing images from rendered documentation")
                            for link in sorted(images):
                                if not fetch(link):
                                    raise ValueError(f"Empty documentation image: {link}")

                            for path in ("companion/connect", "companion/connect.css", "companion/connect.js"):
                                if not fetch(path, authenticated=False):
                                    raise ValueError(f"Missing companion connection asset: {path}")
                            extension = fetch("api/zen/profile/extension")
                            with zipfile.ZipFile(io.BytesIO(extension)) as bundle:
                                if bundle.testzip() is not None:
                                    raise ValueError("Corrupted companion extension ZIP")
                                if "torrentlinker-companion/manifest.json" not in bundle.namelist():
                                    raise ValueError("Companion ZIP has no manifest.json")
                            print(
                                f"Web link smoke test: {len(links)} static, "
                                f"32 guides, {len(images)} images, companion ZIP OK"
                            )
                            print("Native runtime server smoke test: OK")
                            break
                except urllib.error.HTTPError:
                    # A broken authenticated guide / asset is not a startup delay.
                    raise
                except urllib.error.URLError as error:
                    if not isinstance(error.reason, ConnectionRefusedError):
                        raise
                    time.sleep(0.25)
            else:
                raise RuntimeError("TorrentLinker /healthz did not become ready")
        finally:
            process.terminate()
            try:
                output, _ = process.communicate(timeout=12)
            except subprocess.TimeoutExpired:
                process.kill()
                output, _ = process.communicate()
            if process.returncode not in (0, -15):
                print(output.decode(errors="replace")[-5000:])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument(
        "--target", choices=("dsm73-x86_64", "dsm74-x86_64"), default="dsm73-x86_64"
    )
    args = parser.parse_args()
    work = args.workdir.resolve()
    if work.is_relative_to(REPO) or REPO.is_relative_to(work):
        parser.error("Workdir must be outside and must not contain the upstream repository")
    if work.exists() and any(work.iterdir()):
        parser.error("Workdir must not already contain any files")
    work.mkdir(parents=True, exist_ok=True)
    download = work / "downloads"
    download.mkdir()
    payload = work / "payload"
    runtime = payload / "runtime"
    python_file = download / "python.tar.gz"
    get(
        f"https://github.com/astral-sh/python-build-standalone/releases/download/20261026/{PYTHON_ARCHIVE}",
        PYTHON_SHA256, python_file,
    )
    unpack(python_file, work / "python-extracted")
    shutil.move(str(work / "python-extracted/python"), runtime)
    if not (runtime / "bin/python3.12").exists():
        raise ValueError("Standalone Python archive has an unexpected layout")

    sevenzip_file = download / SEVENZIP_ARCHIVE
    get(
        f"https://github.com/ip7z/7zip/releases/download/26.05/{SEVENZIP_ARCHIVE}",
        SEVENZIP_SHA256, sevenzip_file,
    )
    unpack(sevenzip_file, work / "7zip-extracted")
    sevenzip = sorted((work / "7zip-extracted").rglob("7zz"))
    if len(sevenzip) != 1:
        raise ValueError("Official 7-Zip archive must contain precisely one 7zz")
    native_bin = payload / "native/bin"
    native_bin.mkdir(parents=True)
    shutil.copy2(sevenzip[0], native_bin / "7zz")
    (native_bin / "7zz").chmod(0o755)

    source = work / "source"
    source.mkdir()
    shutil.copy2(REPO / "pyproject.toml", source / "pyproject.toml")
    shutil.copytree(REPO / "src", source / "src")
    shutil.copytree(REPO / "docs", source / "docs")
    wheelhouse = work / "wheelhouse"
    wheelhouse.mkdir()
    run(sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir",
        str(wheelhouse), cwd=source)
    application_wheels = list(wheelhouse.glob("torrentlinker-*.whl"))
    if len(application_wheels) != 1:
        raise ValueError("Expected one locally built TorrentLinker wheel")
    application = application_wheels[0]
    run(
        sys.executable, "-m", "pip", "download",
        "--only-binary=:all:", "--prefer-binary",
        "--platform", "manylinux_2_36_x86_64",
        "--platform", "manylinux_2_27_x86_64",
        "--platform", "manylinux2014_x86_64",
        "--platform", "any", "--python-version", "3.12",
        "--implementation", "cp", "--abi", "cp312",
        "--dest", str(wheelhouse), f"{application}[web]", "pymediainfo==7.0.1",
    )
    # The Linux wheel contains libmediainfo itself; a pure-Python wheel does not.
    mediainfo_wheels = list(wheelhouse.glob("pymediainfo-7.0.1-*.whl"))
    if len(mediainfo_wheels) != 1 or "manylinux" not in mediainfo_wheels[0].name:
        raise ValueError("Missing required native pymediainfo manylinux wheel")

    site = runtime / "lib/python3.12/site-packages"
    run(
        sys.executable, "-m", "pip", "install",
        "--no-index", "--no-deps", "--no-compile",
        "--target", str(site), *[str(p) for p in sorted(wheelhouse.glob("*.whl"))],
    )
    # pip --target installs wheel data_files below site-packages/share, while
    # upstream documentation.root() resolves sys.prefix/share/torrentlinker/docs.
    # Bundle the entire immutable upstream docs tree at the expected location.
    shutil.copytree(source / "docs", runtime / "share/torrentlinker/docs")
    run(sys.executable, str(REPO / "synology/tools/audit_web_assets.py"), str(runtime))
    # Validate the entire transitive distribution graph, not merely direct deps.
    import importlib.metadata as md

    distributions = list(md.distributions(path=[str(site)]))
    present = {
        re.sub(r"[-_.]+", "-", d.metadata["Name"]).lower(): d.version
        for d in distributions
    }
    missing = sorted(DIRECT_PACKAGES - set(present))
    if missing:
        raise ValueError(f"Missing direct dependencies: {missing}")
    from packaging.requirements import Requirement
    from packaging.markers import default_environment

    marker_env = default_environment()
    requested_extras = {"torrentlinker": {"web"}, "httpx": {"socks"}, "requests": {"socks"}}
    for distribution in distributions:
        owner = re.sub(r"[-_.]+", "-", distribution.metadata["Name"]).lower()
        for req_text in distribution.requires or ():
            req = Requirement(req_text)
            enabled = False
            for extra in {""} | requested_extras.get(owner, set()):
                marker_env["extra"] = extra
                if req.marker is None or req.marker.evaluate(marker_env):
                    enabled = True
            if not enabled:
                continue
            dep_name = re.sub(r"[-_.]+", "-", req.name).lower()
            if dep_name not in present:
                raise ValueError(
                    f"Missing transitive dependency: {distribution.metadata['Name']} -> {req.name}"
                )
            if req.specifier and not req.specifier.contains(present[dep_name], prereleases=True):
                raise ValueError(f"Bad transitive dependency version: {req}")

    binary_audit = audit_and_bundle_native(payload)
    smoke(runtime, payload)

    # Generate branding assets outside the untouched upstream directory.
    from PIL import Image

    icons = work / "icons"
    icons.mkdir()
    with Image.open(REPO / "src/torrentlinker/assets/icon.png") as original:
        for size in (64, 256):
            frame = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            resized = original.convert("RGBA")
            resized.thumbnail((size, size), Image.Resampling.LANCZOS)
            frame.alpha_composite(resized, ((size - resized.width) // 2, (size - resized.height) // 2))
            frame.save(icons / f"icon{size}.png")

    manifest = {
        "dsm_target": args.target,
        "upstream_commit": (REPO / "synology/upstream.sha").read_text().strip(),
        "python": PYTHON_RELEASE,
        "python_archive_sha256": PYTHON_SHA256,
        "7zip_archive_sha256": SEVENZIP_SHA256,
        "python_distributions": dict(sorted(present.items())),
        "wheels_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(wheelhouse.glob("*.whl"))
        },
        "elf": binary_audit,
        "nas_validation": "NOT YET TESTED ON PHYSICAL DSM HARDWARE",
        "web_links": "static assets, both guide languages, images and companion verified",
    }
    (payload / "synology-build-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    run(
        sys.executable, str(REPO / "synology/tools/build_spk.py"),
        "--payload", str(payload), "--icon64", str(icons / "icon64.png"),
        "--icon256", str(icons / "icon256.png"),
        "--target", args.target,
        "--output-dir", str(work / "dist"),
    )
    print("SPK built with complete wheel manifest; physical NAS acceptance is still required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
