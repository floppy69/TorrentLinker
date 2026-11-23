"""A client address typed without http:// is accepted; a wrong one says which field and why."""

import pytest
from pydantic import ValidationError

from tests.test_web_plan_execution import prepared
from torrentlinker.settings_workspace import SettingsWorkspace, explain_validation
from torrentlinker.web.setup import CLIENT_ADDRESS, CLIENT_PORT, SCGI_ADDRESS, Connection


def connection(host, client="qbittorrent"):
    return Connection(client=client, host=host)


@pytest.mark.parametrize(
    "typed,saved",
    [
        ("192.168.0.50:8080", "http://192.168.0.50:8080"),
        ("  192.168.0.50:8080/  ", "http://192.168.0.50:8080"),
        ("nas", "http://nas"),
        ("seedbox.example.org:9091", "http://seedbox.example.org:9091"),
        ("[::1]:8080", "http://[::1]:8080"),
        ("[2001:db8::7]", "http://[2001:db8::7]"),
        ("https://nas.example.org/qbt", "https://nas.example.org/qbt"),
    ],
)
def test_addresses_without_a_scheme_become_http(typed, saved):
    for client in ("qbittorrent", "deluge", "transmission", "utorrent", "rtorrent"):
        assert connection(typed, client).host == saved


def test_rtorrent_scgi_stays_explicit():
    assert connection("scgi://192.168.0.50:5000", "rtorrent").host == "scgi://192.168.0.50:5000"
    with pytest.raises(ValidationError, match="scgi://host:port"):
        connection("scgi://192.168.0.50", "rtorrent")
    with pytest.raises(ValidationError, match="only for rTorrent"):
        connection("scgi://192.168.0.50:5000", "qbittorrent")


@pytest.mark.parametrize(
    "typed,message",
    [
        ("", CLIENT_ADDRESS),
        ("http://", CLIENT_ADDRESS),
        ("ftp://nas:8080", CLIENT_ADDRESS),
        ("user:secret@nas:8080", CLIENT_ADDRESS),
        ("http://user:secret@nas:8080", CLIENT_ADDRESS),
        ("nas:8080?token=1", CLIENT_ADDRESS),
        ("nas:8080#frag", CLIENT_ADDRESS),
        ("nas:99999", CLIENT_PORT),
        ("nas:0", CLIENT_PORT),
        ("nas:port", CLIENT_PORT),
        ("[::1", CLIENT_PORT),
    ],
)
def test_wrong_addresses_name_the_field_and_what_to_type(typed, message):
    with pytest.raises(ValidationError) as refused:
        connection(typed)
    line = explain_validation(refused.value)
    assert line == message
    assert "secret" not in line
    assert line.startswith("Client address: ")


def test_settings_say_which_field_is_wrong(tmp_path):
    _, setup, _, _ = prepared(tmp_path)
    workspace = SettingsWorkspace(setup)
    for call in (
        lambda: workspace.test_connection("client", {"client": "qbittorrent", "host": "nas:70000"}),
        lambda: workspace.save(
            "connections",
            {
                "client": {"client": "qbittorrent", "host": "ftp://nas", "name": "Studio"},
                "indexer": {"url": setup.settings.indexer.url},
            },
        ),
    ):
        with pytest.raises(ValueError) as refused:
            call()
        assert "Check Settings fields" not in str(refused.value)
        assert str(refused.value).startswith("Client address: ")
    assert SCGI_ADDRESS.startswith("Client address: ")


def test_an_unknown_field_is_named_rather_than_hidden(tmp_path):
    _, setup, _, _ = prepared(tmp_path)
    with pytest.raises(ValueError, match="Invalid value: "):
        SettingsWorkspace(setup).save("general", {"language": "klingon"})
