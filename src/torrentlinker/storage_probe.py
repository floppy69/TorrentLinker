"""Small read-only storage sample. Cached reads are not a sustained disk benchmark."""

from __future__ import annotations

import argparse
import json
import math
import os
import stat
import sys
import time
from collections.abc import Callable
from pathlib import Path
from statistics import median


def _timings(values: list[float]) -> dict[str, float | int]:
    ordered = sorted(values)
    return {
        "samples": len(values),
        "median_ms": round(median(values) * 1000, 3) if values else 0,
        "p95_ms": round(ordered[math.ceil(len(ordered) * 0.95) - 1] * 1000, 3) if values else 0,
    }


def probe_storage(
    folder: Path,
    *,
    max_files: int = 64,
    seconds: float = 5,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    """Sample at most 64 regular files and 1 MiB, without following symlinks.

    The deadline is checked between OS calls; an unresponsive mount can delay a
    single call. Never drops the OS cache, writes media, or inventories the tree.
    """
    if not 1 <= max_files <= 64 or not 0 < seconds <= 30:
        raise ValueError("Use 1–64 files and a duration up to 30 seconds.")
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError("Choose an accessible directory, not a symbolic link.")
    started = clock()
    metadata: list[float] = []
    reads: list[float] = []
    pending = [folder]
    directories = examined = errors = byte_count = files = 0
    while pending and files < max_files and examined < 256 and clock() - started < seconds:
        current = pending.pop()
        directories += 1
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if files >= max_files or examined >= 256 or clock() - started >= seconds:
                        break
                    examined += 1
                    try:
                        before = clock()
                        info = entry.stat(follow_symlinks=False)
                        metadata.append(clock() - before)
                        if stat.S_ISDIR(info.st_mode):
                            pending.append(Path(entry.path))
                        elif stat.S_ISREG(info.st_mode):
                            files += 1
                            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
                            flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
                            before = clock()
                            fd = os.open(entry.path, flags)
                            try:
                                if stat.S_ISREG(os.fstat(fd).st_mode):
                                    byte_count += len(os.read(fd, 16 * 1024))
                            finally:
                                os.close(fd)
                            reads.append(clock() - before)
                    except OSError:
                        errors += 1
        except OSError:
            errors += 1
    elapsed = clock() - started
    return {
        "kind": "local-storage-sample",
        "files_sampled": files,
        "entries_examined": examined,
        "directories_sampled": directories,
        "bytes_read": byte_count,
        "elapsed_seconds": round(elapsed, 3),
        "errors": errors,
        "metadata": _timings(metadata),
        "file_open_read_close": _timings(reads),
        "sample_limit_reached": files == max_files or examined == 256,
        "deadline_reached": elapsed >= seconds,
        "interpretation": "Reads may be cached. This does not measure a remote client's disk "
        "or establish a safe API request rate. "
        "Bulk client reads adapt to their own response latency.",
    }


def main(args: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--output", type=Path, help="Save the report, useful for the Windows exe")
    options = parser.parse_args(args)
    try:
        report = probe_storage(options.folder)
    except ValueError as error:
        parser.error(str(error))
    content = json.dumps(report, indent=2) + "\n"
    if options.output:
        options.output.write_text(content, encoding="utf-8")
    elif sys.stdout is not None:
        print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
