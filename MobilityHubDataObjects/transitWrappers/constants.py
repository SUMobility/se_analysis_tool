from enum import Enum

class ModeClassification(Enum) :
    HIGH_COMFORT = 0
    BUS = 1
    OTHER = 2

# GTFS Constants
TRAM = "TRAM"
METRO = "METRO"
RAIL = "RAIL"
BUS = "BUS"
FERRY = "FERRY"
CABLE_CAR = "CABLE_CAR"
AERIAL = "AERIAL"
FUNICULAR = "FUNICULAR"
TROLLEYBUS = "TROLLEYBUS"
MONORAIL = "MONORAIL"

MODE_CLASSIFICATION_MAP = {
    TRAM: ModeClassification.HIGH_COMFORT,
    METRO: ModeClassification.HIGH_COMFORT,
    RAIL: ModeClassification.HIGH_COMFORT,
    BUS: ModeClassification.BUS,
    FERRY: ModeClassification.HIGH_COMFORT,
    CABLE_CAR: ModeClassification.OTHER,
    AERIAL: ModeClassification.OTHER,
    FUNICULAR: ModeClassification.OTHER,
    TROLLEYBUS: ModeClassification.BUS,
    MONORAIL: ModeClassification.HIGH_COMFORT,
}

HIGH_COMFORT_MODES = [TRAM, METRO, FERRY, MONORAIL, AERIAL]

ROUTE_PRIORITY_MAP = {
    RAIL: 0,
    METRO: 1,
    FERRY: 2,
    MONORAIL: 3,
    FUNICULAR: 4,
    AERIAL: 5,
    CABLE_CAR: 6,
    TRAM: 7,
    TROLLEYBUS: 8,
    BUS: 9,
}
#TODO: should funiculars be included? (this only matters for pgh I think)

ROUTE_TYPE_TO_ROUTE_DISPLAY_NAME_MAP = {
    TRAM: "Tram",
    METRO: "Metro",
    RAIL: "Rail",
    BUS: "Bus",
    FERRY: "Ferry",
    CABLE_CAR: "Surface Cable Car",
    AERIAL: "Aerial Transit",
    FUNICULAR: "Funicular",
    TROLLEYBUS: "Trolleybus",
    MONORAIL: "Monorail",
}
MODE_COLOR_MAP = {
    ROUTE_TYPE_TO_ROUTE_DISPLAY_NAME_MAP[TRAM]: "#faa0dd",
    ROUTE_TYPE_TO_ROUTE_DISPLAY_NAME_MAP[METRO]: "#f779cf",
    ROUTE_TYPE_TO_ROUTE_DISPLAY_NAME_MAP[RAIL]: "#fa5cc7",
    ROUTE_TYPE_TO_ROUTE_DISPLAY_NAME_MAP[BUS]: "#f5c9e7",
    ROUTE_TYPE_TO_ROUTE_DISPLAY_NAME_MAP[FERRY]: "#c47cad",
    ROUTE_TYPE_TO_ROUTE_DISPLAY_NAME_MAP[CABLE_CAR]: "#c47cad",
    ROUTE_TYPE_TO_ROUTE_DISPLAY_NAME_MAP[AERIAL]: "#c47cad",
    ROUTE_TYPE_TO_ROUTE_DISPLAY_NAME_MAP[FUNICULAR]: "#c47cad",
    ROUTE_TYPE_TO_ROUTE_DISPLAY_NAME_MAP[TROLLEYBUS]: "#f5c9e7",
    ROUTE_TYPE_TO_ROUTE_DISPLAY_NAME_MAP[MONORAIL]: "#c47cad"
}
GTFS_ROUTE_TYPE_TO_ID_MAP = {
    0: TRAM,
    1: METRO,
    2: RAIL,
    3: BUS,
    4: FERRY,
    5: CABLE_CAR,
    6: AERIAL,
    7: FUNICULAR,
    11: TROLLEYBUS,
    12: MONORAIL,
}