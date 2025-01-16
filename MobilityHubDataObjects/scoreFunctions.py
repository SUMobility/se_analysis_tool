import numpy as np
from MobilityHubDataObjects.utils import safe_is_na
from typing import Callable

def get_score_constant_value(value: float) -> Callable[[], float]:
    return lambda: value

def get_proportional_score(max_value: int, max_score: int) -> Callable[[float], float]: 
    return lambda n: n / max_value * max_score
