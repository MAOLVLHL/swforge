import pytest

from swforge import catalog


def test_hex_bolt_values_match_gb_5783():
    m8 = catalog.hex_bolt("M8")
    assert (m8.d, m8.s, m8.k) == (8.0, 13.0, 5.3)
    assert 40 in m8.lengths


def test_designations_are_case_insensitive():
    assert catalog.hex_nut("m10").s == 16.0


def test_nut_height_grows_with_diameter():
    heights = [row.m for row in catalog.HEX_NUTS.values()]
    assert heights == sorted(heights)


def test_washer_inner_diameter_clears_the_bolt():
    for row in catalog.WASHERS.values():
        assert row.inner > row.d


def test_unknown_designation_lists_known_sizes():
    with pytest.raises(KeyError) as excinfo:
        catalog.hex_bolt("M7")
    assert "known sizes" in str(excinfo.value)
    assert "M6" in str(excinfo.value)


def test_socket_screw_socket_is_smaller_than_head():
    for row in catalog.SOCKET_SCREWS.values():
        assert row.socket < row.dk


def test_summary_mentions_every_standard():
    text = catalog.summary()
    for standard in ("GB/T 5783", "GB/T 6170", "GB/T 97.1", "GB/T 70.1"):
        assert standard in text
