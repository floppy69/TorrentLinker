"""End-to-end check against a real Indexer and qBittorrent. Opt-in only.

    TL_LIVE=1 pytest tests/test_live.py -s     # key from Settings, or TL_INDEXER_KEY=...

Searches and verifies the ebook below; it only Reseeds with TL_LIVE_RESEED=1.
Never writes to the library.
"""

import os
import time
from pathlib import Path

import pytest

from torrentlinker.domain import ContentKind, LibraryFolder
from torrentlinker.indexer import Indexer
from torrentlinker.matching import IgnoreList, MatchRules
from torrentlinker.reseed import check_verifications, start_reseed
from torrentlinker.review import check_candidates, search_candidates
from torrentlinker.scan import scan
from torrentlinker.store import Store

pytestmark = pytest.mark.skipif(not os.environ.get("TL_LIVE"), reason="set TL_LIVE=1")


def indexer_key() -> str:
    """TL_INDEXER_KEY, else the key saved from the app's Settings (system keyring)."""
    from torrentlinker.credentials import get_secret
    from torrentlinker.gui.settings_common import INDEXER_API_KEY

    key = os.environ.get("TL_INDEXER_KEY") or get_secret(INDEXER_API_KEY)
    if not key:
        pytest.skip("enter the c411 API key in Settings → Connections, or set TL_INDEXER_KEY")
    return key


LIBRARY = Path(os.environ.get("TL_LIVE_LIBRARY", "/windocs/E-Book"))
ITEM_NAME = os.environ.get("TL_LIVE_ITEM", "Le joueur d'echecs - Stefan Zweig.epub")
RULES = MatchRules(0.02, 0.5, IgnoreList.default())
URL = os.environ.get("TL_INDEXER_URL", "https://c411.org/api/torznab")


def test_ebook_is_found_and_matches_with_a_rename(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    indexer = Indexer(URL, indexer_key(), cache=store)
    item = next(i for i in scan(LibraryFolder(LIBRARY)) if i.path.name == ITEM_NAME)

    caps = indexer.caps()
    found = search_candidates(indexer, item, ContentKind.EBOOK, (), caps.modes)
    results = check_candidates(indexer, item, found, RULES)
    matches = [v for v in results if v.match]
    for v in results:
        print(v.candidate.title, v.candidate.size, "MATCH" if v.match else "")

    assert matches, "no Full Match found"
    best = matches[0]
    assert best.match is not None and best.meta is not None
    print("renames:", best.match.renames)

    if os.environ.get("TL_LIVE_RESEED"):
        from torrentlinker.qbit import QbitApi

        qbit = QbitApi(
            os.environ["TL_QBIT_HOST"], os.environ["TL_QBIT_USER"], os.environ["TL_QBIT_PASS"]
        )
        start_reseed(qbit, store, item, best.meta, best.match, best.meta.infohash)
        for _ in range(60):
            if outcomes := check_verifications(qbit, store):
                assert outcomes[item.path].verified
                return
            time.sleep(1)
        pytest.fail("Verification did not finish within a minute")
