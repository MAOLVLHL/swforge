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


def test_the_suggestion_lists_sizes_in_diameter_order():
    """A string sort reads "M10, M12, M3", which nobody scans for M6."""
    with pytest.raises(KeyError) as excinfo:
        catalog.hex_bolt("M7")
    # str(KeyError) wraps the message in quotes, so strip the closing one.
    listed = str(excinfo.value).split("known sizes: ")[1].rstrip("'\"").split(", ")
    assert listed == list(SPAN), listed


def test_socket_screw_socket_is_smaller_than_head():
    for row in catalog.SOCKET_SCREWS.values():
        assert row.socket < row.dk


def test_summary_mentions_every_standard():
    text = catalog.summary()
    for standard in ("GB/T 5783", "GB/T 6170", "GB/T 97.1", "GB/T 70.1"):
        assert standard in text


#: The range the four standards share.  A table that stops at M20 makes a bolt
#: above it hand-typed, which is exactly what a catalogue is supposed to avoid.
SPAN = ("M3", "M4", "M5", "M6", "M8", "M10", "M12", "M16", "M20", "M24", "M30")


@pytest.mark.parametrize(
    "table",
    [
        catalog.HEX_BOLTS,
        catalog.HEX_NUTS,
        catalog.WASHERS,
        catalog.SOCKET_SCREWS,
    ],
    ids=["bolts", "nuts", "washers", "socket screws"],
)
def test_every_table_spans_the_same_designations(table):
    assert sorted(table) == sorted(SPAN), (
        "a designation missing from one table is a fastener with no counterpart: "
        "M24 threads into a nut that the nut table does not carry"
    )


def test_a_nut_passes_the_bolt_of_its_own_designation():
    for designation, bolt in catalog.HEX_BOLTS.items():
        bore = catalog.nut_bore(designation)
        assert bore > bolt.d, (
            f"{designation}: a {bore:g} mm bore cannot pass the {bolt.d:g} mm "
            "shank of the bolt it is catalogued for"
        )
        assert bore < catalog.hex_nut(designation).s, (
            f"{designation}: a {bore:g} mm bore leaves no nut across the "
            f"{catalog.hex_nut(designation).s:g} mm flats"
        )


def test_head_height_grows_with_diameter():
    heights = [row.k for row in catalog.HEX_BOLTS.values()]
    assert heights == sorted(heights), (
        "the tables are ordered by designation, and a smaller screw with a "
        "taller head would make the ordering a lie"
    )


def test_a_catalogued_length_fits_inside_the_bolt_it_belongs_to():
    """Every offered length has to leave a shank, not just a head.

    length is what the builder extends past the head, so a length shorter than
    the head height is a bolt whose shank never clears the material it holds.
    """
    for row in catalog.HEX_BOLTS.values():
        for length in row.lengths:
            assert length > row.k, (
                f"{row.designation} x {length:g}: the {row.k:g} mm head is "
                "longer than the length it is catalogued with"
            )
