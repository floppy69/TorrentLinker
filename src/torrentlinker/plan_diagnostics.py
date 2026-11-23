"""Reasons a Plan is empty, shared by desktop, web and automation callers."""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class PlanIssue:
    code: str
    count: int = 0


def issue_text(issue: PlanIssue, translate: Callable[[str], str] = lambda text: text) -> str:
    messages = {
        "catalogue_empty": (
            "The Catalogue is empty. Fetch the selected categories, then make a Plan again."
        ),
        "category": (
            "{0} cached torrents are outside the selected categories. Refresh the selected "
            "categories or broaden the selection."
        ),
        "unknown_category": (
            "{0} cached torrents have no category. Refresh their metadata before planning."
        ),
        "in_client": (
            "{0} torrents are already in the target client. Choose other categories or "
            "refresh the Catalogue for new torrents."
        ),
        "no_seeders": (
            "{0} torrents have no known seeders. Refresh the selected categories to update "
            "swarm counts."
        ),
        "excluded_title": (
            "{0} torrents match your excluded words. Review the Plan exclusions in Settings."
        ),
        "no_folder": (
            "{0} torrents have no Download Folder for their category. Set its folder in "
            "Settings, or choose a category with a folder."
        ),
        "on_disk": (
            "{0} torrents appear to be on disk already. Search them in the Library to Reseed them."
        ),
        "torrent_cap": (
            "Your total torrent cap is reached. Raise it in Settings > Zen to add more torrents."
        ),
        "plan_cap": "The Plan torrent limit is zero. Increase it or disable the limit.",
        "minimum_torrents": (
            "This Plan contains fewer than the requested minimum of {0} torrents. "
            "Widen the filters, increase available space or lower the minimum count."
        ),
        "filters": "{0} torrents do not match the size or seeder filters. Widen the Plan filters.",
        "zen_class": (
            "Your Zen class does not earn Zen from seeding. Choose a seeding class in "
            "Settings > Zen."
        ),
        "seed_hours": "Seeding time is set to zero. Set the hours per day in Settings > Zen.",
        "no_gain": (
            "No candidate adds estimated Zen with this profile. Review the Zen settings or "
            "optimize for Note."
        ),
        "disk_space": (
            "{0} torrents exceed the available disk space after the free-space reserve. Free "
            "space or review the reserve in Settings."
        ),
        "download_limit": (
            "{0} torrents exceed the Plan download limit. Increase the download limit or "
            "choose smaller torrents."
        ),
        "client_budget": (
            "No torrent fits the selected clients' download budgets. Increase a client budget "
            "or choose smaller torrents."
        ),
        "no_candidates": (
            "No eligible torrent remains for this Plan. Review the selected categories and filters."
        ),
    }
    return translate(messages.get(issue.code, messages["no_candidates"])).format(issue.count)
