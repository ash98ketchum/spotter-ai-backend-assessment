import pandas as pd
import requests
import io
import sqlite3

print("Downloading US cities dataset from GitHub...")
url = "https://raw.githubusercontent.com/kelvins/US-Cities-Database/main/csv/us_cities.csv"
try:
    cities_df = pd.read_csv(url)
except Exception as e:
    print(f"Failed to download from kelvins repo: {e}")
    print("Falling back to another dataset...")
    try:
        url2 = "https://raw.githubusercontent.com/plotly/datasets/master/us-cities-top-1k.csv"
        cities_df = pd.read_csv(url2)
        cities_df = cities_df.rename(columns={'lat': 'LATITUDE', 'lon': 'LONGITUDE', 'State': 'STATE_CODE', 'City': 'CITY'})
    except Exception as e2:
        print(f"Failed fallback: {e2}")
        exit(1)

# Ensure columns are named correctly
if 'LATITUDE' not in cities_df.columns:
    print("Columns in cities_df:", cities_df.columns)
    exit(1)

cities_df = cities_df.rename(columns={
    'CITY': 'city',
    'STATE_CODE': 'state_id',
    'LATITUDE': 'lat',
    'LONGITUDE': 'lng'
})

cities_df['city_lower'] = cities_df['city'].str.lower()
cities_df['state_id_lower'] = cities_df['state_id'].str.lower()
# Drop duplicates taking the first one
cities_df = cities_df.drop_duplicates(subset=['city_lower', 'state_id_lower'])

print("Loading truck stops...")
trucks_df = pd.read_csv('fuel-prices-for-be-assessment (1).csv')

trucks_df['city_lower'] = trucks_df['City'].str.lower()
trucks_df['state_id_lower'] = trucks_df['State'].str.lower()

print("Merging datasets...")
merged_df = pd.merge(trucks_df, cities_df, how='left', left_on=['city_lower', 'state_id_lower'], right_on=['city_lower', 'state_id_lower'])

missing_coords = merged_df[merged_df['lat'].isna()]
print(f"Total truck stops: {len(trucks_df)}")
print(f"Stops successfully mapped to coordinates: {len(trucks_df) - len(missing_coords)}")
print(f"Stops missing coordinates: {len(missing_coords)}")

# Clean up
clean_df = merged_df.dropna(subset=['lat', 'lng'])
cols_to_keep = ['OPIS Truckstop ID', 'Truckstop Name', 'Address', 'City', 'State', 'Rack ID', 'Retail Price', 'lat', 'lng']
clean_df = clean_df[cols_to_keep]

print("Saving to SQLite and JSON...")
clean_df.to_json('truck_stops_with_coords.json', orient='records', indent=2)

conn = sqlite3.connect('truck_stops.db')
clean_df.to_sql('truck_stops', conn, if_exists='replace', index=False)
conn.close()
print("Data preprocessing complete!")
