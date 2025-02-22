from enum import Enum
import datetime as dt

NO_MODE = "NA"

class ModeClassification(Enum) :
    HIGH_COMFORT = 0
    BUS = 1
    OTHER = 2

class Mode(Enum):
    NA = "NA"
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
    Mode.NA: "#f5c9e7",
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

CONFIG_MORNING_PEAK_START = "morning_peak_start"
CONFIG_MORNING_PEAK_END = "peak_end"
CONFIG_OFF_PEAK_START = "off_peak_start"
CONFIG_OFF_PEAK_END = "off_peak_end"
CONFIG_EVENING_PEAK_START = "evening_peak_start"
CONFIG_EVENING_PEAK_END = "evening_peak_end"
CONFIG_PEAK_WEIGHT = "peak_weight"
CONFIG_HEADWAY_PERCENTILE = "headway_percentile"
CONFIG_MIN_TRIPS_TO_INCLUDE_SERVICE_PATTERN = "service_pattern_cutoff"
CONFIG_MIN_TRIPS_TO_CALCULATE_HEADWAY = "trip_cutoff"
PERIOD_MORNING_PEAK_NAME = "morning_peak"
PERIOD_EVENING_PEAK_NAME = "evening_peak"
PERIOD_OFF_PEAK_NAME = "off_peak"
MIN_TRIPS = 5

CONFIG_CLUSTERING_ENABLED = "cluster"
CONFIG_CLUSTERING_DISTANCE_SAME_ROUTE = "same_route_distance"
CONFIG_CLUSTERING_DISTANCE_BUS_TO_BUS = "bus_to_bus_distance"
CONFIG_CLUSTERING_DISTANCE_HIGH_COMFORT_TO_HIGH_COMFORT = "high_comfort_to_high_comfort"
CONFIG_CLUSTERING_DISTANCE_BUS_TO_HIGH_COMFORT = "bus_to_high_comfort"


ARBITRARY_DATE = dt.date(1970,1,1)

DEFAULT_FEED_CONFIG = {
    CONFIG_MORNING_PEAK_START: dt.time(hour=7), #TODO: do we also want t
    CONFIG_MORNING_PEAK_END: dt.time(hour=9, minute=0),
    CONFIG_OFF_PEAK_START: dt.time(hour=9, minute=0),
    CONFIG_OFF_PEAK_END: dt.time(hour=16,minute=0),
    CONFIG_EVENING_PEAK_START: dt.time(hour=16, minute=0),
    CONFIG_EVENING_PEAK_END: dt.time(hour=18),
    CONFIG_PEAK_WEIGHT: 0.5,
    CONFIG_HEADWAY_PERCENTILE: 80,
    CONFIG_MIN_TRIPS_TO_INCLUDE_SERVICE_PATTERN: 5,
    CONFIG_MIN_TRIPS_TO_CALCULATE_HEADWAY: 5,
    CONFIG_CLUSTERING_ENABLED: True,
    CONFIG_CLUSTERING_DISTANCE_SAME_ROUTE: 200,
    CONFIG_CLUSTERING_DISTANCE_BUS_TO_BUS: 80,
    CONFIG_CLUSTERING_DISTANCE_HIGH_COMFORT_TO_HIGH_COMFORT: 250,
    CONFIG_CLUSTERING_DISTANCE_BUS_TO_HIGH_COMFORT: 500
}