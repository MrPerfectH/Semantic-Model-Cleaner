"""Backend naming convention repeatability remains supported without its UI."""
import pytest

from semantic_model_cleaner import review_policy


@pytest.mark.parametrize('case', ['preserve', 'title', 'pascal', 'snake'])
@pytest.mark.parametrize('prefix,suffix', [('QA ', ''), ('', ' USD'), ('QA ', ' USD')])
def test_literal_affixes_do_not_accumulate(case, prefix, suffix):
    rule = {'find': '', 'replace': '', 'prefix': prefix, 'suffix': suffix, 'case': case}
    first = review_policy._transform('netRevenue', rule)
    assert review_policy._transform(first, rule) == first
    assert not prefix or first.startswith(prefix)
    assert not suffix or first.endswith(suffix)
