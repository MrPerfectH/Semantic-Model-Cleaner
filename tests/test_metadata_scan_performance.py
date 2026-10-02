"""Large metadata text must not copy its remaining text per token."""

import pytest

from semantic_model_cleaner import analyzer


class SliceCountingText(str):
    """Measure Python string slices without relying on machine timing."""

    def __new__(cls, value):
        instance = super().__new__(cls, value)
        instance.copied_characters = 0
        return instance

    def __getitem__(self, key):
        result = super().__getitem__(key)
        if isinstance(key, slice):
            self.copied_characters += len(result)
        return result


@pytest.mark.parametrize("filler_count", [128, 512])
def test_qualified_reference_scan_has_linear_text_copy_budget(filler_count):
    # Long DAX and metadata expressions contain long runs of punctuation,
    # identifiers and Unicode between references. Include a non-BMP character
    # so copied suffixes also represent the expensive wide-string case.
    filler = "\t\tcaption: Zażółć gęślą jaźń; 日本語; αβ; 😀; translated_label\n"
    text = SliceCountingText(
        "metadata: Sales[Revenue]\n"
        + filler * filler_count
        + "\tmetadata: 'Customer''s 地域'[Label]]Text]\n"
        + filler * filler_count
        + "\tmetadata: Salesą[Amount]\n"
    )

    assert analyzer._extract_dax_qualified_refs_from_text(text) == {
        ("Sales", "Revenue"),
        ("Customer's 地域", "Label]Text"),
        ("Salesą", "Amount"),
    }
    # Allow several complete copies; repeatedly slicing the remaining suffix
    # consumes hundreds of input lengths even at the smaller fixture size.
    assert text.copied_characters <= 4 * len(text), (
        f"Copied {text.copied_characters:,} characters while scanning "
        f"{len(text):,} characters of text"
    )
