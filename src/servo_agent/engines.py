"""Servo's official builds: install one, and find the ones installed.

Servo publishes a prebuilt engine with every release on GitHub, each archive
with a SHA-256 beside it. `servo-agent install-servo` downloads the archive for
this machine, checks it against that SHA-256, and unpacks it into servo-agent's
data directory, where :func:`servo_agent.browser.find_servoshell` looks. So a
working engine is one command, with nothing to compile.

The checksum is published by the same release as the archive. It catches a
corrupt or truncated download; it is not a signature, so it trusts GitHub and
Servo's release process exactly as much as downloading the archive by hand does.
"""
from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import tarfile
import tempfile
from collections.abc import Callable
from pathlib import Path

import requests

RELEASES_API = "https://api.github.com/repos/servo/servo/releases"
RELEASES_PAGE = "https://github.com/servo/servo/releases"

_VERSION_DIR = re.compile(r"servo-(\d+)\.(\d+)\.(\d+)")


class EngineInstallError(RuntimeError):
    """The engine could not be installed; the message says why and what to do."""


def engines_dir() -> Path:
    """Where installed engines live: ``$XDG_DATA_HOME/servo-agent/engines``."""
    data = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(data) / "servo-agent" / "engines"


def asset_name(system: str | None = None, machine: str | None = None) -> str:
    """The release archive for this machine, e.g. ``servo-x86_64-linux-gnu.tar.gz``.

    Only Linux archives are installed for now: Servo ships macOS as a disk image
    and Windows as an installer, which this command does not unpack yet.
    """
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    arch = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}
    if system == "Linux" and machine in arch:
        return f"servo-{arch[machine]}-linux-gnu.tar.gz"
    raise EngineInstallError(
        f"no installable Servo build for {system} {machine}. Download one from "
        f"{RELEASES_PAGE} and set $SERVOSHELL to its servoshell binary."
    )


def installed(root: Path | None = None) -> list[tuple[tuple[int, int, int], Path]]:
    """Installed engines as ``((major, minor, patch), servoshell)``, oldest first."""
    root = root or engines_dir()
    found = []
    for d in root.glob("servo-*"):
        m = _VERSION_DIR.fullmatch(d.name)
        exe = d / "servoshell"
        if m and exe.is_file() and os.access(exe, os.X_OK):
            found.append(((int(m[1]), int(m[2]), int(m[3])), exe))
    return sorted(found)


def newest_installed(root: Path | None = None) -> Path | None:
    found = installed(root)
    return found[-1][1] if found else None


def _get(url: str, **kw):
    headers = {"Accept": "application/vnd.github+json"}
    # GitHub allows 60 unauthenticated API calls an hour per address; CI has a token.
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.get(url, headers=headers, timeout=kw.pop("timeout", 60), **kw)
    resp.raise_for_status()
    return resp


def _extract(archive: Path, into: Path) -> None:
    """Unpack, refusing members that would land outside ``into``."""
    try:
        with tarfile.open(archive) as tf:
            if hasattr(tarfile, "data_filter"):  # 3.12+, and 3.10.12+ / 3.11.4+
                tf.extractall(into, filter="data")
                return
            root = into.resolve()
            for m in tf.getmembers():
                target = (into / m.name).resolve()
                if root not in target.parents and target != root:
                    raise EngineInstallError(f"archive member escapes the install dir: {m.name}")
                if m.issym() or m.islnk() or m.isdev():
                    raise EngineInstallError(f"archive member is not a plain file: {m.name}")
            tf.extractall(into)  # every member was checked above
    except tarfile.TarError as e:
        raise EngineInstallError(f"refused to unpack {archive.name}: {e}") from e


def install(version: str | None = None, root: Path | None = None,
            say: Callable[[str], None] = print) -> Path:
    """Install Servo's official build (the latest release, or ``version``).

    Returns the installed ``servoshell``. A version already installed is not
    downloaded again.
    """
    root = root or engines_dir()
    name = asset_name()
    where = f"{RELEASES_API}/tags/v{version.lstrip('v')}" if version else f"{RELEASES_API}/latest"
    try:
        release = _get(where, timeout=30).json()
    except requests.RequestException as e:
        raise EngineInstallError(f"could not read the Servo release at {where}: {e}") from e
    tag = release.get("tag_name", "")
    if not _VERSION_DIR.fullmatch(f"servo-{tag.lstrip('v')}"):
        raise EngineInstallError(f"unexpected Servo release tag {tag!r}")
    target = root / f"servo-{tag.lstrip('v')}"
    exe = target / "servoshell"
    if exe.is_file():
        say(f"Servo {tag} is already installed: {exe}")
        return exe
    urls = {a["name"]: a["browser_download_url"] for a in release.get("assets", [])}
    if name not in urls or f"{name}.sha256" not in urls:
        raise EngineInstallError(f"Servo {tag} has no {name} with a .sha256 beside it")

    expected = _get(urls[f"{name}.sha256"], timeout=30).text.split()[0].lower()
    root.mkdir(parents=True, exist_ok=True)
    # Stage inside `root` so the final move is a rename on one filesystem, and a
    # failed or interrupted install leaves nothing that looks installed.
    with tempfile.TemporaryDirectory(prefix=".install-", dir=root) as tmp:
        archive = Path(tmp) / name
        digest = hashlib.sha256()
        say(f"downloading {urls[name]}")
        with _get(urls[name], stream=True, timeout=120) as resp, open(archive, "wb") as f:
            for chunk in resp.iter_content(1 << 20):
                digest.update(chunk)
                f.write(chunk)
        if digest.hexdigest() != expected:
            raise EngineInstallError(
                f"{name} does not match its published SHA-256 "
                f"(expected {expected}, got {digest.hexdigest()}); nothing was installed"
            )
        say(f"SHA-256 matches the release's: {expected}")
        staging = Path(tmp) / "unpacked"
        _extract(archive, staging)
        unpacked = staging / "servo"  # the archive's one top-level directory
        if not (unpacked / "servoshell").is_file():
            raise EngineInstallError(f"{name} has no servo/servoshell inside")
        shutil.move(str(unpacked), str(target))
    say(f"installed Servo {tag}: {exe}")
    return exe
