"""Details and bounded image retry through the shared public service."""

import httpx
import pytest

from tests.test_torrent_details import DETAILS, fake_indexer, png


def test_details_keep_safe_markup_and_retry_images_without_refetching_metadata(monkeypatch):
    from torrentlinker.details_workspace import DetailsWorkspace

    calls = []
    blocked = True

    def image_response(request):
        nonlocal blocked
        calls.append(request)
        if blocked:
            blocked = False
            return httpx.Response(503)
        return httpx.Response(200, content=png(), headers={"Content-Type": "image/png"})

    monkeypatch.setattr(
        "torrentlinker.torrent_details.net.client",
        lambda **kwargs: httpx.Client(transport=httpx.MockTransport(image_response), **kwargs),
    )
    service = DetailsWorkspace(fake_indexer(lambda r: httpx.Response(200, json=DETAILS)))
    with pytest.raises(ValueError, match="valid hash"):
        service.image("invalid", 0)
    detail = service.load("a" * 40)
    assert "<h2>Synopsis</h2>" in detail["description"]
    assert detail["nfo"].startswith("┌── NFO")
    assert detail["files"] == (("Folder/film.mkv", 1024),)
    first = service.image("a" * 40, 0)
    assert first["error"] and first["retry_after"] == 0
    retried = service.image("a" * 40, 0)
    assert retried["src"].startswith("data:image/png;base64,")
    assert service.image("a" * 40, 0) == retried
    assert len(calls) == 2
    assert all("authorization" not in request.headers for request in calls)


def test_image_host_cooldown_applies_to_other_images_until_retry_time(monkeypatch):
    from torrentlinker.details_workspace import DetailsWorkspace

    now = [100.0]
    calls = []
    payload = {
        "description": '<img src="https://limited.example/a.png"><img src="https://limited.example/b.png">'
    }

    def response(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "120"})
        return httpx.Response(200, content=png(), headers={"Content-Type": "image/png"})

    monkeypatch.setattr(
        "torrentlinker.torrent_details.net.client",
        lambda **kwargs: httpx.Client(transport=httpx.MockTransport(response), **kwargs),
    )
    service = DetailsWorkspace(
        fake_indexer(lambda r: httpx.Response(200, json=payload)), clock=lambda: now[0]
    )
    service.load("a" * 40)
    assert service.image("a" * 40, 0)["retry_after"] == 120
    assert service.image("a" * 40, 1)["retry_after"] == 120
    assert len(calls) == 1
    now[0] += 121
    assert service.image("a" * 40, 1)["src"].startswith("data:image/png;")


def test_image_retry_recovers_after_more_than_twenty_four_details(monkeypatch):
    from torrentlinker.details_workspace import DetailsWorkspace

    monkeypatch.setattr(
        "torrentlinker.torrent_details.net.client",
        lambda **kw: httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, content=png(), headers={"content-type": "image/png"})
            ),
            **kw,
        ),
    )
    loaded = []

    def details(request):
        loaded.append(request.url.path)
        return httpx.Response(200, json=DETAILS)

    service = DetailsWorkspace(fake_indexer(details))
    for n in range(25):
        service.load(f"{n:040x}")
    assert service.image("0" * 40, 0)["src"].startswith("data:image/png")
    assert loaded[0] == loaded[-1]
