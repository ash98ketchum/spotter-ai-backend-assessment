import sqlite3
import pandas as pd
import numpy as np

conn = sqlite3.connect('truck_stops.db')
df = pd.read_sql("SELECT * FROM truck_stops", conn)
print("Total stops:", len(df))
ca_stops = df[df['State'] == 'CA']
print("CA stops:", len(ca_stops))
print("Sample CA stop:", ca_stops.head(1))
conn.close()
