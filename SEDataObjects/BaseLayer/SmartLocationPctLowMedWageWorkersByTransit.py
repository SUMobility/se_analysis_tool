from SEDataObjects.BaseLayer.constants import (
    SMART_LOCATION_PCT_LOW_MED_WAGE_WORKERS_BY_TRANSIT,
    SMART_LOCATION_PCT_LOW_MED_WAGE_WORKERS_BY_TRANSIT_NAME,
)
from SEDataObjects.BaseLayer.entities import BaseLayerSmartLocation


class SmartLocationPctLowMedWageWorkersByTransit(BaseLayerSmartLocation):
    metric_field_id = SMART_LOCATION_PCT_LOW_MED_WAGE_WORKERS_BY_TRANSIT
    metric_alias = SMART_LOCATION_PCT_LOW_MED_WAGE_WORKERS_BY_TRANSIT_NAME