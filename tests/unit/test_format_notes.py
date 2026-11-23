"""The Meta-format notes file stays well-formed and in sync with build_status."""

from pathlib import Path

import yaml

NOTES = Path(__file__).parents[2] / "docs" / "meta-format-notes.yaml"
STATUSES = {"confirmed", "conflicting", "unconfirmed"}


def test_every_note_has_value_status_source_and_note() -> None:
    notes = yaml.safe_load(NOTES.read_text(encoding="utf-8"))["status_webhook"]
    assert notes
    for name, entry in notes.items():
        assert entry["status"] in STATUSES, name
        assert "value" in entry and entry["source"].startswith("https://"), name
        assert entry["note"].strip(), name


def test_notes_describe_the_formats_build_status_implements() -> None:
    notes = yaml.safe_load(NOTES.read_text(encoding="utf-8"))["status_webhook"]
    assert notes["pricing_model_current"]["value"] == "PMP"
    assert notes["pricing_model_legacy"]["value"] == "CBP"
