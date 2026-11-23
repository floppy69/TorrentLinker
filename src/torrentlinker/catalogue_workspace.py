"""Category coverage shared by the desktop and owner Web catalogue hosts."""

from dataclasses import dataclass

from torrentlinker.catalogue_sync import (
    LISTED_ROOTS,
    ROOT_FEED,
    ROOT_NAMES,
    TORZNAB_ONLY_ROOTS,
    root_categories,
)
from torrentlinker.store import Store


@dataclass(frozen=True)
class CategoryCard:
    root: int
    name: str
    ours: int
    site: int | None
    state: str
    fetchable: bool = True
    updated_at: float | None = None


def catalogue_cards(
    store: Store,
    *,
    adult: bool = False,
    current: int | None = None,
    phase: str = "running",
    single_root: int | None = None,
) -> list[CategoryCard]:
    known, unknown = store.catalogue_root_counts()
    owner: dict[int, int] = {}
    for root in ROOT_NAMES:
        for category in root_categories(root):
            owner.setdefault(category, root)
    counts = dict(known)
    for category, count in unknown.items():
        if (holder := owner.get(category)) is not None:
            counts[holder] = counts.get(holder, 0) + count
    order = {root: i for i, root in enumerate(LISTED_ROOTS)}
    cards = []
    for root in [*LISTED_ROOTS, *sorted(TORZNAB_ONLY_ROOTS)]:
        fetchable = root not in TORZNAB_ONLY_ROOTS
        if not fetchable and not adult:
            continue
        feed = store.feed_state(f"{ROOT_FEED}{root}")
        waiting = (
            current is not None
            and single_root is None
            and order.get(root, -1) > order.get(current, -1)
        )
        state = (
            "cache"
            if not fetchable
            else phase
            if root == current
            else "waiting"
            if waiting
            else "paused"
            if feed.started_at is not None
            else "done"
            if feed.updated_at is not None
            else "never"
        )
        cards.append(
            CategoryCard(
                root,
                ROOT_NAMES[root],
                counts.get(root, 0),
                (feed.count if feed.updated_at is not None or feed.count else None)
                if fetchable
                else None,
                state,
                fetchable,
                feed.updated_at,
            )
        )
    return cards
