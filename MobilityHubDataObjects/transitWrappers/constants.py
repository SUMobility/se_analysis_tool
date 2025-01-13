from enum import Enum

NO_MODE = "NA"

class ModeClassification(Enum) :
    HIGH_COMFORT = 0
    BUS = 1
    OTHER = 2

class Mode(Enum):
    TRAM = "Tram"
    METRO = "Metro"
    RAIL = "Rail"
    BUS = "Bus"
    FERRY = "Ferry"
    CABLE_CAR = "Surface Cable Car"
    AERIAL = "Aerial Transit"
    FUNICULAR = "Funicular"
    TROLLEYBUS = "Trolleybus"
    MONORAIL = "Monorail"

MODE_CLASSIFICATION_MAP = {
    Mode.TRAM: ModeClassification.HIGH_COMFORT,
    Mode.METRO: ModeClassification.HIGH_COMFORT,
    Mode.RAIL: ModeClassification.HIGH_COMFORT,
    Mode.BUS: ModeClassification.BUS,
    Mode.FERRY: ModeClassification.HIGH_COMFORT,
    Mode.CABLE_CAR: ModeClassification.OTHER,
    Mode.AERIAL: ModeClassification.OTHER,
    Mode.FUNICULAR: ModeClassification.OTHER,
    Mode.TROLLEYBUS: ModeClassification.BUS,
    Mode.MONORAIL: ModeClassification.HIGH_COMFORT,
}

HIGH_COMFORT_MODES = [Mode.TRAM, Mode.METRO, Mode.FERRY, Mode.MONORAIL, Mode.AERIAL]

ROUTE_PRIORITY_MAP = {
    Mode.RAIL: 0,
    Mode.METRO: 1,
    Mode.FERRY: 2,
    Mode.MONORAIL: 3,
    Mode.FUNICULAR: 4,
    Mode.AERIAL: 5,
    Mode.CABLE_CAR: 6,
    Mode.TRAM: 7,
    Mode.TROLLEYBUS: 8,
    Mode.BUS: 9,
}
#TODO: should funiculars be included? (this only matters for pgh I think)

ROUTE_TYPE_TO_ROUTE_DISPLAY_NAME_MAP = {
    Mode.TRAM: "Tram",
    Mode.METRO: "Metro",
    Mode.RAIL: "Rail",
    Mode.BUS: "Bus",
    Mode.FERRY: "Ferry",
    Mode.CABLE_CAR: "Surface Cable Car",
    Mode.AERIAL: "Aerial Transit",
    Mode.FUNICULAR: "Funicular",
    Mode.TROLLEYBUS: "Trolleybus",
    Mode.MONORAIL: "Monorail",
}
MODE_COLOR_MAP = {
    Mode.TRAM: "#faa0dd",
    Mode.METRO: "#f779cf",
    Mode.RAIL: "#fa5cc7",
    Mode.BUS: "#f5c9e7",
    Mode.FERRY: "#c47cad",
    Mode.CABLE_CAR: "#c47cad",
    Mode.AERIAL: "#c47cad",
    Mode.FUNICULAR: "#c47cad",
    Mode.TROLLEYBUS: "#f5c9e7",
    Mode.MONORAIL: "#c47cad"
}
GTFS_ROUTE_TYPE_TO_ID_MAP = {
    0: Mode.TRAM,
    1: Mode.METRO,
    2: Mode.RAIL,
    3: Mode.BUS,
    4: Mode.FERRY,
    5: Mode.CABLE_CAR,
    6: Mode.AERIAL,
    7: Mode.FUNICULAR,
    11: Mode.TROLLEYBUS,
    12: Mode.MONORAIL,
}