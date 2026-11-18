"""Base layers: loaded before any source adapter, idempotent, no signals."""
from territory.layers.parcels import load_parcels
from territory.layers.planning_areas import load_planning_areas
from territory.layers.zoning import load_zoning

# Registry order is the run order: planning areas -> parcels -> zoning.
LAYERS = {
    "planning_areas": load_planning_areas,
    "parcels": load_parcels,
    "zoning": load_zoning,
}
