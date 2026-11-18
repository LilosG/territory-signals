import pytest

from territory.owner_data.attom import AttomOwnerProvider
from territory.owner_data.base import NotConfiguredError
from territory.owner_data.sample import SampleOwnerProvider


def test_sample_provider_is_stable_and_labeled():
    p = SampleOwnerProvider()
    a, b = p.get_owner("3000012345"), SampleOwnerProvider().get_owner("3000012345")
    assert a == b
    assert a.is_sample is True and a.provider == "sample"
    assert a.owner_name == "Sample Owner 2345"
    assert p.get_sales_history("3000012345") == p.get_sales_history("3000012345")
    assert all(s.is_sample and s.provider == "sample" for s in p.get_sales_history("3000012345"))
    assert p.get_owner("3000012345") != p.get_owner("3000099999")


def test_sample_bulk_owners():
    owners = SampleOwnerProvider().bulk_owners(["3000012345", "3000067890"])
    assert [o.apn for o in owners] == ["3000012345", "3000067890"]
    assert all(o.is_sample for o in owners)


def test_attom_requires_key(monkeypatch):
    monkeypatch.delenv("ATTOM_API_KEY", raising=False)
    with pytest.raises(NotConfiguredError):
        AttomOwnerProvider()
