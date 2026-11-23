"""Upload diagnostic translations remain consistent."""

import pytest


@pytest.mark.parametrize("language", ["en", "fr"])
def test_completeness_review_preserves_fields_and_unknown_diagnostics(qapp, language):
    from torrentlinker import i18n
    from torrentlinker.gui.upload_rules import stored_rule_text
    from torrentlinker.upload_presentation import assess

    translators = i18n.install(qapp, language)
    try:
        findings = assess({"category": 10, "subcategory": 51, "nfo": "Release notes"})[
            "missing_fields"
        ]
        for row in findings:
            rendered = stored_rule_text(f"{row['field']}: {row['message']}")
            assert not rendered.startswith(row["field"] + ":")
            if language == "en":
                assert rendered == row["message"]
            else:
                assert rendered != row["message"]
                if row["field"].startswith("nfo."):
                    assert "Conservez les NFO d'origine sans les modifier" in rendered
                    assert "obtenez un NFO d'origine complet" in rendered
                if row["field"] == "description.size":
                    assert "[b]Taille totale :[/b] valeur." in rendered
        for finding in (
            "description.image: New validation rule: <details> & values",
            "nfo.codec: NFO conflict: 'FLAC'; file facts require 'MP3'.",
            "Old review prose without a diagnostic code",
        ):
            assert stored_rule_text(finding) == finding
    finally:
        for translator in translators:
            qapp.removeTranslator(translator)


def test_french_review_explains_conflicts_and_preserves_evidence(qapp):
    from copy import deepcopy

    from tests.test_upload_completeness import presentation_review_findings
    from torrentlinker import i18n
    from torrentlinker.gui.upload_rules import stored_rule_text

    findings = presentation_review_findings()
    before = deepcopy(findings)
    translators = i18n.install(qapp, "fr")
    try:
        messages = [stored_rule_text(f"{r['field']}: {r['message']}") for r in findings]
        for row, message in zip(findings, messages, strict=True):
            assert message != f"{row['field']}: {row['message']}"
            assert not message.startswith(row["field"] + ":")
        text = "\n".join(messages)
        for evidence in (
            "Piece <one> & two.stl",
            "Book <one> & two.epub",
            "en, de",
            "Lewis Carroll",
            "Someone else",
            "'MP3'",
            "'FLAC'",
            "2",
            "03:42",
        ):
            assert evidence in text
        assert "Conservez le NFO d'origine" in text
        assert "ne modifiez pas sa langue déclarée" in text
        assert "Description, piste ou chapitre 2" in text
        assert "NFO, piste ou chapitre 2" in text
        assert findings == before
    finally:
        for translator in translators:
            qapp.removeTranslator(translator)
