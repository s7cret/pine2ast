from pathlib import Path

from openpine_contracts import list_schema_ids


def test_contracts_pin_and_catalog() -> None:
    text = Path("pyproject.toml").read_text(encoding="utf-8")
    assert (
        "openpine-contracts @ git+https://github.com/s7cret/openpine-contracts.git@"
        "51e32ebaaf02eecb81443e8ca7e89b2543cb25a3"
        in text
    )
    ids = list_schema_ids()
    assert "openpine.frontend.v2" in ids
    assert "openpine.generated_artifact.v2" in ids
    assert "openpine.intent.v2" in ids
