# General constants


from enum import Enum


GEODESIC_CRS = 4326
MILES_TO_METERS_FACTOR = 1609.34
METERS_TO_MILES_FACTOR = 1/MILES_TO_METERS_FACTOR


class StopClassification(Enum):
    NOT_MOBILITY_HUB = "Not Mobility Hub"
    BRANCH = "Branch"
    TRUNK = "Trunk"







