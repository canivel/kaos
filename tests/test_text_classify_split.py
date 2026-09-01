"""Synthetic text_classify: default sizes silently emptied the test set."""
import kaos.metaharness.benchmarks.text_classify  # noqa: F401
from kaos.metaharness.benchmarks import get_benchmark


def test_synthetic_split_has_nonempty_test_set():
    b = get_benchmark("text_classify")            # defaults, synthetic data
    assert len(b.get_search_set()) == 16
    assert len(b.get_test_set()) == 16            # was 0 before the cap

def test_explicit_sizes_respected_when_data_suffices():
    b = get_benchmark("text_classify", search_size=10, test_size=10)
    assert len(b.get_search_set()) == 10
    assert len(b.get_test_set()) == 10
