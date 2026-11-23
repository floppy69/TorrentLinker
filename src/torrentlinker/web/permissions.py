"""What each route needs, declared on the route and checked before its handler runs.

    @app.get("/api/media")
    @needs(*WATCH)  # any one of these Permissions

    @needs(Audience.SIGNED_IN)  # any actor, Viewers included
    @needs(Permission.SEARCH, action={"state", "detail"})  # and only these path values

A route without a declaration is the Owner's alone, so a new route is safe by default.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, MutableMapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypeVar

from starlette.routing import BaseRoute, Match

from torrentlinker.accounts import Actor, Permission

Endpoint = TypeVar("Endpoint", bound=Callable[..., Any])


class Audience(StrEnum):
    PUBLIC = "public"  # no sign-in at all
    SIGNED_IN = "signed-in"  # any actor
    ACCOUNT_HOLDER = "account-holder"  # the Owner or a Member, never a Viewer


@dataclass(frozen=True)
class Need:
    any_of: frozenset[Permission | Audience]
    only: tuple[tuple[str, frozenset[str]], ...] = ()

    def admits(self, actor: Actor, path_params: dict[str, Any]) -> bool:
        if actor.owner:
            return True
        if any(str(path_params.get(name)) not in values for name, values in self.only):
            return False
        return any(self.met(need, actor) for need in self.any_of)

    @staticmethod
    def met(need: Permission | Audience, actor: Actor) -> bool:
        if need is Audience.ACCOUNT_HOLDER:
            return not actor.viewer
        if isinstance(need, Audience):
            return True
        return actor.holds(need)


def needs(*any_of: Permission | Audience, **only: Iterable[str]) -> Callable[[Endpoint], Endpoint]:
    """Declare what a route needs: any one of these, and path values limited to `only`."""
    if not any_of:
        raise ValueError("Declare at least one Permission or Audience.")
    need = Need(
        frozenset(any_of), tuple((name, frozenset(values)) for name, values in only.items())
    )

    def declare(endpoint: Endpoint) -> Endpoint:
        endpoint.need = need  # type: ignore[attr-defined]
        return endpoint

    return declare


def declared(
    routes: Iterable[BaseRoute], scope: MutableMapping[str, Any]
) -> tuple[Need | None, dict]:
    """The declaration of the route this request reaches, with its path values."""
    for route in routes:
        match, child = route.matches(scope)
        if match is Match.FULL:
            endpoint = getattr(route, "endpoint", None)
            return getattr(endpoint, "need", None), child.get("path_params", {})
    return None, {}


def allowed(routes: Iterable[BaseRoute], scope: MutableMapping[str, Any], actor: Actor) -> bool:
    if actor.owner:
        return True
    need, path_params = declared(routes, scope)
    return need is not None and need.admits(actor, path_params)


def public(routes: Iterable[BaseRoute], scope: MutableMapping[str, Any]) -> bool:
    """Whether the route this request reaches answers without any sign-in."""
    need, _ = declared(routes, scope)
    return need is not None and Audience.PUBLIC in need.any_of
