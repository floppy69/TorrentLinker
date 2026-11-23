"""Upgrade evidence accepts new defaults, but never loses historical settings."""

import pytest

from scripts.check_upgrade import assert_preserved


def test_new_profile_defaults_do_not_invalidate_preserved_settings():
    before = {"client_profiles": [{"id": "nas", "host": "https://fixture.invalid"}]}
    after = {"client_profiles": [{**before["client_profiles"][0], "reseed_layout": "preserve"}]}
    assert_preserved(after, before)


@pytest.mark.parametrize("change", ["remove-key", "change-value", "remove-client", "reorder"])
def test_nested_setting_loss_is_rejected_without_exposing_values(change):
    before = {"client_profiles": [{"host": "private-host"}, {"host": "second-host"}]}
    after = {"client_profiles": [dict(p) for p in before["client_profiles"]]}
    if change == "remove-key":
        del after["client_profiles"][0]["host"]
    elif change == "change-value":
        after["client_profiles"][0]["host"] = "changed-host"
    elif change == "remove-client":
        after["client_profiles"].pop()
    else:
        after["client_profiles"].reverse()
    with pytest.raises(AssertionError) as error:
        assert_preserved(after, before)
    assert "client_profiles" in str(error.value)
    assert "private-host" not in str(error.value)
