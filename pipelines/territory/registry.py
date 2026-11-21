"""Adapter registry. Order is the run order for `--source all`."""
from territory.sources.code_enforcement import CodeEnforcementAdapter
from territory.sources.dev_permits import DevPermitsAdapter
from territory.sources.fire_zones import FireZonesAdapter
from territory.sources.stro_licenses import StroLicensesAdapter
from territory.sources.tax_default import TaxDefaultAdapter
from territory.sources.upzoning_estimate import UpzoningEstimateAdapter

ADAPTERS = {
    a.source_key: a
    for a in (StroLicensesAdapter, DevPermitsAdapter, CodeEnforcementAdapter, TaxDefaultAdapter,
              UpzoningEstimateAdapter, FireZonesAdapter)
}
