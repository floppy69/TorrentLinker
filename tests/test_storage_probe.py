import json

from torrentlinker.storage_probe import main, probe_storage


def test_probe_is_bounded_and_does_not_change_content(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    data = b"x" * 32768
    for i in range(100):
        (root / f"{i}.bin").write_bytes(data)
    before = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in root.iterdir()}
    report = probe_storage(root)
    assert report["files_sampled"] == 64
    assert report["bytes_read"] == 1024 * 1024
    assert report["sample_limit_reached"]
    assert report["errors"] == 0
    assert {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in root.iterdir()} == before
    assert all(p.read_bytes() == data for p in root.iterdir())
    assert str(root) not in json.dumps(report)


def test_probe_does_not_follow_symlinks(tmp_path):
    import pytest

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("untouched")
    root = tmp_path / "media"
    root.mkdir()
    try:
        (root / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks unavailable")
    report = probe_storage(root)
    assert report["files_sampled"] == 0
    assert report["directories_sampled"] == 1


def test_probe_writes_a_report_only_when_requested(tmp_path):
    output = tmp_path / "report.json"
    assert main([str(tmp_path), "--output", str(output)]) == 0
    assert json.loads(output.read_text())["kind"] == "local-storage-sample"
