"""Large translation metadata must not copy its remaining text per token."""

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


@pytest.mark.parametrize("translation_count", [128, 512])
def test_translation_reference_scan_has_linear_text_copy_budget(translation_count):
    # Real cultures contain long runs of punctuation, identifiers and Unicode
    # captions between references. Include a non-BMP character so copied suffixes
    # also represent the expensive wide-string case seen in customer metadata.
    caption = "\t\tcaption: Zażółć gęślą jaźń; 日本語; αβ; 😀; translated_label\n"
    metadata = SliceCountingText(
        "culture pl-PL\n\tmetadata: Sales[Revenue]\n"
        + caption * translation_count
        + "\tmetadata: 'Customer''s 地域'[Label]]Text]\n"
        + caption * translation_count
        + "\tmetadata: Salesą[Amount]\n"
    )

    assert analyzer._extract_item_keys_from_metadata_text(metadata) == {
        ("Sales", "Revenue"),
        ("Customer's 地域", "Label]Text"),
        ("Salesą", "Amount"),
    }
    # Allow several complete copies; repeatedly slicing the remaining suffix
    # consumes hundreds of input lengths even at the smaller fixture size.
    assert metadata.copied_characters <= 4 * len(metadata), (
        f"Copied {metadata.copied_characters:,} characters while scanning "
        f"{len(metadata):,} characters of metadata"
    )
