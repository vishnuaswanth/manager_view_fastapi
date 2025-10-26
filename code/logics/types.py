# types.py

import pandas as pd
from sqlalchemy.types import TypeDecorator, Text
from io import StringIO

class DataFrameJSON(TypeDecorator):
    """
    Automatically serialize/deserialize pandas DataFrame (MultiIndex supported)
    """
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, pd.DataFrame):
            return value.to_json(orient='split')
        raise ValueError("Expected a pandas DataFrame")

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        df = pd.read_json(StringIO(value), orient='split')
        if df.empty:
            return df 
        if isinstance(df.columns[0], (list, tuple)):
            df.columns = pd.MultiIndex.from_tuples(df.columns)
        # columns = pd.MultiIndex.from_arrays(df.columns)
        # df = pd.DataFrame(df.values, columns=columns).reset_index(drop=True)
        return df
