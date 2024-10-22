import numpy as np
from MobilityHubDataObjects.utils import safe_is_na


def score_transit_stops(headway_dict: dict) -> float:
    if safe_is_na(headway_dict):
        return np.nan
    score = 0
    for headway in headway_dict.values():
        if headway == -1:
            score += 0
        else:
            # weird fugly sigmoid just as a demo
            score += max(0, -10 * (1 / (1 + np.e ** (-(headway - 17)/5))) + 10.3229)
    return score

def get_score_constant_value(value: float): # TODO: add type hint
    return lambda: value

def get_proportional_score(max_value: int, max_score: int): # TODO: add type hint
    return lambda n: n / max_value * max_score
