"""Installing Servo's official build, against a fake release served locally. No network."""
from __future__ import annotations

import hashlib
import http.server
import io
import json
import tarfile
import threading
from pathlib import Path

import pytest

import servo_agent.engines as engines
from servo_agent.engines import EngineInstallError

ASSET = "servo-x86_64-linux-gnu.tar.gz"


def _tarball(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755 if name.endswith("/servoshell") else 0o644
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.fixture
def release(tmp_path, monkeypatch):
    """Serve one fake Servo release (v0.7.0) over HTTP and point the installer at it."""
    site = tmp_path / "site"
    hits: list[str] = []

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(site), **k)

        def log_message(self, *_a):
            pass

        def do_GET(self):  # noqa: N802 — the stdlib's name
            hits.append(self.path)
            return super().do_GET()

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def publish(archive: bytes, checksum: str | None = None, tag: str = "v0.7.0") -> None:
        (site / "dl").mkdir(parents=True, exist_ok=True)
        (site / "api" / "tags").mkdir(parents=True, exist_ok=True)
        (site / "dl" / ASSET).write_bytes(archive)
        digest = checksum or hashlib.sha256(archive).hexdigest()
        (site / "dl" / f"{ASSET}.sha256").write_text(f"{digest}  {ASSET}\n")
        doc = {"tag_name": tag, "assets": [
            {"name": ASSET, "browser_download_url": f"{base}/dl/{ASSET}"},
            {"name": f"{ASSET}.sha256", "browser_download_url": f"{base}/dl/{ASSET}.sha256"},
        ]}
        (site / "api" / "latest").write_text(json.dumps(doc))
        (site / "api" / "tags" / tag).write_text(json.dumps(doc))

    monkeypatch.setattr(engines, "RELEASES_API", f"{base}/api")
    monkeypatch.setattr(engines.platform, "system", lambda: "Linux")
    monkeypatch.setattr(engines.platform, "machine", lambda: "x86_64")
    yield publish, hits, tmp_path / "engines"
    server.shutdown()


GOOD = {"servo/servoshell": b"#!/bin/sh\necho Servo\n", "servo/resources/prefs.json": b"{}"}


def test_installs_the_latest_release_and_checks_its_checksum(release) -> None:
    publish, _hits, root = release
    publish(_tarball(GOOD))

    exe = engines.install(root=root, say=lambda _m: None)

    assert exe == root / "servo-0.7.0" / "servoshell"
    assert exe.read_bytes() == GOOD["servo/servoshell"]
    assert exe.stat().st_mode & 0o100, "servoshell must stay executable"
    assert engines.newest_installed(root) == exe


def test_a_version_already_installed_is_not_downloaded_again(release) -> None:
    publish, hits, root = release
    publish(_tarball(GOOD))
    engines.install(version="0.7.0", root=root, say=lambda _m: None)
    hits.clear()

    engines.install(version="0.7.0", root=root, say=lambda _m: None)

    assert not any(h.startswith("/dl/") for h in hits)


def test_a_checksum_mismatch_installs_nothing(release) -> None:
    publish, _hits, root = release
    publish(_tarball(GOOD), checksum="0" * 64)

    with pytest.raises(EngineInstallError, match="does not match its published SHA-256"):
        engines.install(root=root, say=lambda _m: None)
    assert engines.installed(root) == []
    assert [p.name for p in root.iterdir()] == []  # the staging directory is gone too


def test_an_archive_member_outside_the_install_dir_is_refused(release) -> None:
    publish, _hits, root = release
    publish(_tarball({**GOOD, "../escaped": b"x"}))

    with pytest.raises(EngineInstallError):
        engines.install(root=root, say=lambda _m: None)
    assert not (root.parent / "escaped").exists()
    assert engines.installed(root) == []


def test_installed_lists_versions_oldest_first_and_skips_strays(tmp_path) -> None:
    for name in ("servo-0.6.0", "servo-0.10.1", "servo-0.7.0", "servo-nightly", ".install-x"):
        d = tmp_path / name
        d.mkdir()
        exe = d / "servoshell"
        exe.write_text("")
        exe.chmod(0o755)
    (tmp_path / "servo-0.9.0").mkdir()  # no binary inside

    versions = [v for v, _ in engines.installed(tmp_path)]

    assert versions == [(0, 6, 0), (0, 7, 0), (0, 10, 1)]
    assert engines.newest_installed(tmp_path) == tmp_path / "servo-0.10.1" / "servoshell"


def test_asset_names_by_platform() -> None:
    assert engines.asset_name("Linux", "x86_64") == "servo-x86_64-linux-gnu.tar.gz"
    assert engines.asset_name("Linux", "aarch64") == "servo-aarch64-linux-gnu.tar.gz"
    with pytest.raises(EngineInstallError, match=r"set \$SERVOSHELL"):
        engines.asset_name("Darwin", "arm64")


def test_engines_dir_follows_xdg_data_home(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert engines.engines_dir() == Path(tmp_path) / "servo-agent" / "engines"
