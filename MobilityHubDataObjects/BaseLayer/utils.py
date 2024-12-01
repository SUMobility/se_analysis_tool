import pandas as pd
import geopandas as gpd


def split_county_fips(county_fips: pd.Series) -> tuple[pd.Series]:
    return county_fips.str.slice(0,2), county_fips.str.slice(2,6)
