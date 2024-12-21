import numpy as np
from MobilityHubDataObjects.constants import HIGH_COMFORT_MODES
from MobilityHubDataObjects.utils import safe_is_na
from typing import Callable

def score_transit_stops(headway_string: str, mode: str) -> float:
    if safe_is_na(headway_string) or headway_string == "":
        return np.nan
    score = 0
    for headway in headway_string.split(","):
        if float(headway) == -1:
            score += 0
        else:
            # weird fugly sigmoid just as a demo
            score += max(0, -10 * (1 / (1 + np.e ** (-(float(headway) - 17)/5))) + 10.3229) # <- lovely consts
            if mode in HIGH_COMFORT_MODES:
                score += 10
    return score

def get_score_constant_value(value: float) -> Callable[[], float]:
    return lambda: value

def get_proportional_score(max_value: int, max_score: int) -> Callable[[float], float]: 
    return lambda n: n / max_value * max_score
