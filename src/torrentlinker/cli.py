"""Choose desktop or server before importing optional UI dependencies."""

from __future__ import annotations

import sys


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "diagnose-storage":
        from torrentlinker.storage_probe import main as probe

        return probe(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        del sys.argv[1]
        from torrentlinker.web.server import main as serve

        return serve()
    if len(sys.argv) > 1 and sys.argv[1] == "mcp":
        del sys.argv[1]
        from torrentlinker.agent.stdio import main as bridge

        return bridge()
    from torrentlinker.app import main as desktop

    return desktop()
