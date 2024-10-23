import shapely
import math
from typing import Callable

def get_linear_decay_function(zero_distance: float) -> Callable[[float], float]:
    return lambda distance: 0 if distance > zero_distance else 1 - distance / zero_distance

def get_nonsense_decay_function(spam: float, zero_distance: float) -> Callable[[float], float] :
    return lambda distance: 0 if distance > zero_distance else math.abs(math.sin(spam * distance))

