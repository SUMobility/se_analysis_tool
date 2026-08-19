from SEDataObjects.BaseLayer.constants import (
    SMART_LOCATION_PCT_POP_ACCESSIBLE_BY_TRANSIT,
    SMART_LOCATION_PCT_POP_ACCESSIBLE_BY_TRANSIT_NAME,
)
from SEDataObjects.BaseLayer.entities import BaseLayerSmartLocation


class SmartLocationPctPopAccessibleByTransit(BaseLayerSmartLocation):
    metric_field_id = SMART_LOCATION_PCT_POP_ACCESSIBLE_BY_TRANSIT
    metric_alias = SMART_LOCATION_PCT_POP_ACCESSIBLE_BY_TRANSIT_NAME