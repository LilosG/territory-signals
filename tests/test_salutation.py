"""Salutation formatter: owner name patterns (assessor LAST FIRST style) -> greeting line."""
import re

import pytest

from territory.salutation import format_salutation, pretty_address

SITUS = "2307 CALLE DE LA GARZA"
FB = "To the owners of 2307 Calle De La Garza,"

# (pattern description, owner_name, is_sample, expected salutation)
CASES = [
    ("LAST FIRST", "SMITH JOHN", False, "Dear John Smith,"),
    ("LAST FIRST MIDDLE-INITIAL", "SMITH JOHN A", False, "Dear John Smith,"),
    ("LAST FIRST & FIRST", "SMITH JOHN & MARY", False, "Dear John and Mary Smith,"),
    ("LAST FIRST I & FIRST I", "SMITH JOHN A & MARY B", False, "Dear John and Mary Smith,"),
    ("LAST FIRST & LAST FIRST (same last)", "SMITH JOHN & SMITH MARY", False, "Dear John and Mary Smith,"),
    ("three owners", "SMITH JOHN & MARY & JAMES", False, "Dear John, Mary and James Smith,"),
    ("comma after surname", "SMITH, JOHN A", False, "Dear John Smith,"),
    ("AND spelled out", "SMITH JOHN AND MARY", False, "Dear John and Mary Smith,"),
    ("marital code JT", "SMITH JOHN & MARY JT", False, "Dear John and Mary Smith,"),
    ("marital code H/W", "SMITH JOHN A & MARY B H/W", False, "Dear John and Mary Smith,"),
    ("suffix Jr", "SMITH JOHN A JR", False, "Dear John Smith Jr,"),
    ("hyphenated surname", "SMITH-JONES MARY", False, "Dear Mary Smith-Jones,"),
    ("apostrophe surname", "O'BRIEN PATRICK", False, "Dear Patrick O'Brien,"),
    ("Mc surname", "MCDONALD ANN", False, "Dear Ann McDonald,"),
    ("particle surname", "DE LA CRUZ MARIA", False, "Dear Maria De La Cruz,"),
    ("individual trustee TR", "SMITH JOHN TR", False, "Dear John Smith,"),
    ("individual trustee TRUSTEE", "SMITH JOHN A TRUSTEE", False, "Dear John Smith,"),
    ("two individual trustees", "SMITH JOHN & MARY TRS", False, "Dear John and Mary Smith,"),
    ("family trust name", "SMITH FAMILY TRUST", False, "To the Trustee of the Smith Family Trust,"),
    ("THE family trust", "THE SMITH FAMILY TRUST", False, "To the Trustee of the Smith Family Trust,"),
    ("living trust with trustee code", "SMITH FAMILY LIVING TRUST TR", False,
     "To the Trustee of the Smith Family Living Trust,"),
    ("abbreviated revocable trust", "SMITH FAM REV TRUST", False, "To the Trustee of the Smith Family Revocable Trust,"),
    ("trust with date clause", "SMITH FAMILY TRUST DTD 3/4/2001", False, "To the Trustee of the Smith Family Trust,"),
    ("owners' names in a trust", "SMITH JOHN & MARY TRUST", False, "To the Trustee of the John and Mary Smith Trust,"),
    ("LLC", "ABC HOLDINGS LLC", False, FB),
    ("corporation", "PACIFIC COAST PROPERTIES INC", False, FB),
    ("LP / partners", "LA JOLLA PARTNERS LP", False, FB),
    ("government", "CITY OF SAN DIEGO", False, FB),
    ("sample owner (flag)", "SMITH JOHN", True, FB),
    ("sample owner (name)", "Sample Owner 2345", False, FB),
    ("empty name", "", False, FB),
    ("missing name", None, False, FB),
    ("et al (other owners unknown)", "SMITH JOHN ETAL", False, FB),
    ("estate is never mentioned", "SMITH JOHN ESTATE OF", False, FB),
    ("deceased marker", "SMITH JOHN DECD", False, FB),
    ("initial-only first name", "SMITH J", False, FB),
    ("single token", "SMITH", False, FB),
    ("different surnames (ambiguous)", "SMITH JOHN & JONES MARY", False, FB),
    ("first+middle name (ambiguous)", "SMITH MARY ANN", False, FB),
    ("mixed case is not trusted", "John Smith", False, FB),
    ("digits in a person name", "SMITH JOHN 2ND", False, FB),
]


@pytest.mark.parametrize("desc,name,is_sample,expected", CASES, ids=[c[0] for c in CASES])
def test_salutation_patterns(desc, name, is_sample, expected):
    assert format_salutation(name, SITUS, is_sample).text == expected


def test_at_least_twelve_distinct_patterns_are_covered():
    assert len({c[0] for c in CASES}) >= 12 and len(CASES) >= 12


def test_flags_say_whether_the_owner_name_was_used():
    assert format_salutation("SMITH JOHN", SITUS).uses_owner_name is True
    assert format_salutation("SMITH FAMILY TRUST", SITUS).uses_owner_name is True
    assert format_salutation("ABC HOLDINGS LLC", SITUS).uses_owner_name is False
    assert format_salutation("SMITH JOHN", SITUS, is_sample=True).uses_owner_name is False
    assert format_salutation("SMITH JOHN", SITUS).kind == "person"
    assert format_salutation("SMITH JOHN & MARY", SITUS).kind == "couple"
    assert format_salutation("SMITH JOHN TR", SITUS).kind == "trustee"
    assert format_salutation("SMITH FAMILY TRUST", SITUS).kind == "trust"


def test_fallback_without_an_address_is_still_a_greeting():
    assert format_salutation("ABC HOLDINGS LLC", None).text == "To the property owner,"
    assert format_salutation("ABC HOLDINGS LLC", "").text == "To the property owner,"


def test_no_salutation_mentions_death_or_circumstances():
    for _d, name, sample, _e in CASES:
        text = format_salutation(name, SITUS, sample).text.lower()
        assert not re.search(r"estate|deceas|dece|late |probate|heir|inherit|death", text)


def test_pretty_address():
    assert pretty_address("2307 CALLE DE LA GARZA") == "2307 Calle De La Garza"
    assert pretty_address("100 N PROSPECT ST") == "100 N Prospect St"
    assert pretty_address(None) == ""
