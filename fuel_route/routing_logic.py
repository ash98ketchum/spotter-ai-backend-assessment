import concurrent.futures
import requests
import math
import numpy as np
import pandas as pd
import sqlite3
from sklearn.neighbors import BallTree
import os
from django.conf import settings

# Load stations into memory for fast querying
BASE_DIR = getattr(settings, 'BASE_DIR', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(BASE_DIR, 'truck_stops.db')

try:
    conn = sqlite3.connect(DB_PATH)
    STATIONS_DF = pd.read_sql("SELECT * FROM truck_stops", conn)
    conn.close()
    
    # Haversine metric requires inputs in radians: [lat, lon]
    stations_rad = np.deg2rad(STATIONS_DF[['lat', 'lng']].values)
    STATIONS_TREE = BallTree(stations_rad, metric='haversine')
except Exception as e:
    print(f"Failed to load truck_stops.db: {e}")
    STATIONS_DF = None
    STATIONS_TREE = None

def haversine_distance(lon1, lat1, lon2, lat2):
    """Calculate distance in miles between two points"""
    R = 3958.8  # Earth radius in miles
    lon1, lat1, lon2, lat2 = map(math.radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    return R * c

def geocode(location_string):
    """Geocode a string to [lon, lat] using Nominatim"""
    url = f"https://nominatim.openstreetmap.org/search?q={requests.utils.quote(location_string)}&format=json&limit=1"
    headers = {'User-Agent': 'Spotter-AI-Assessment'}
    res = requests.get(url, headers=headers)
    if res.status_code == 200:
        data = res.json()
        if data:
            return [float(data[0]['lon']), float(data[0]['lat'])]
    return None

def point_to_segment_distance(p, v, w):
    """
    Return minimum distance between point p and line segment vw,
    and the projection of p onto vw as a fraction of the segment.
    (All in cartesian coordinates, approximate for small distances).
    """
    l2 = (v[0] - w[0])**2 + (v[1] - w[1])**2
    if l2 == 0:
        return math.dist(p, v), 0
    t = max(0, min(1, ((p[0] - v[0]) * (w[0] - v[0]) + (p[1] - v[1]) * (w[1] - v[1])) / l2))
    proj = [v[0] + t * (w[0] - v[0]), v[1] + t * (w[1] - v[1])]
    return math.dist(p, proj), t

def get_route_and_stations(start_str, finish_str):
    # Fire both geocoding requests simultaneously
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future_start = executor.submit(geocode, start_str)
        future_finish = executor.submit(geocode, finish_str)
        
        start_coords = future_start.result()
        finish_coords = future_finish.result()
        
    if not start_coords or not finish_coords:
        return None, {"error": "Could not geocode one or both locations."}, 0.0
        
    osrm_url = f"http://router.project-osrm.org/route/v1/driving/{start_coords[0]},{start_coords[1]};{finish_coords[0]},{finish_coords[1]}?overview=full&geometries=geojson"
    osrm_res = requests.get(osrm_url)
    if osrm_res.status_code != 200:
        return None, {"error": "OSRM routing failed."}, 0.0
        
    data = osrm_res.json()
    if data['code'] != 'Ok':
        return None, {"error": "No route found."}, 0.0
        
    route = data['routes'][0]
    geometry = route['geometry']
    coords = geometry['coordinates']
    total_distance_miles = route['distance'] * 0.000621371
    
    if STATIONS_TREE is None or STATIONS_DF is None or len(STATIONS_DF) == 0:
        return None, {"error": "No station data available."}, 0.0
    
    # Ensure coords is a numpy array for fast math: shape (N, 2)
    coords_arr = np.array(coords)
    
    # Extract lons and lats and convert to radians in one go
    lon1, lat1 = np.radians(coords_arr[:-1, 0]), np.radians(coords_arr[:-1, 1])
    lon2, lat2 = np.radians(coords_arr[1:, 0]), np.radians(coords_arr[1:, 1])
    
    # Vectorized Haversine calculation for all segments at once
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = np.sin(dlat/2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2)**2
    c = 2 * np.arcsin(np.sqrt(a))
    
    # Array of every segment distance in miles
    segment_distances = 3958.8 * c 
    
    # Array of cumulative distances from the start (inserts a 0 at the beginning)
    cumulative_distances = np.insert(np.cumsum(segment_distances), 0, 0)
    
    # Downsample route to query BallTree (taking every 20th coordinate is sufficient for broad filtering)
    sample_points = coords_arr[::20]
        
    # Query BallTree (radius in radians, 20 miles = 20 / 3958.8 rad)
    radius_rad = 20 / 3958.8
    query_pts = np.deg2rad([[p[1], p[0]] for p in sample_points])
    indices = STATIONS_TREE.query_radius(query_pts, r=radius_rad)
    
    unique_indices = set()
    for arr in indices:
        unique_indices.update(arr)
        
    nearby_stations = STATIONS_DF.iloc[list(unique_indices)].copy()
    
    if nearby_stations.empty:
        return geometry, [], total_distance_miles
        
    # 2. 1D Mapping: snap nearby stations to route
    station_routes = []
    route_rad = np.deg2rad([[p[1], p[0]] for p in coords]) 
    route_tree = BallTree(route_rad, metric='haversine')
    
    station_rad = np.deg2rad(nearby_stations[['lat', 'lng']].values)
    distances, indices = route_tree.query(station_rad, k=1) 
    
    for idx, (df_idx, row) in enumerate(nearby_stations.iterrows()):
        closest_coord_idx = indices[idx][0]
        best_d_along_route = cumulative_distances[closest_coord_idx]
        
        dist_to_route_miles = distances[idx][0] * 3958.8
        
        if dist_to_route_miles < 15:
            station_routes.append({
                'id': row['OPIS Truckstop ID'],
                'name': row['Truckstop Name'],
                'price': row['Retail Price'],
                'lat': row['lat'],
                'lng': row['lng'],
                'distance_along_route': best_d_along_route
            })
            
    station_routes.sort(key=lambda x: x['distance_along_route'])
    return geometry, station_routes, total_distance_miles

def optimize_fuel(stations, total_distance, max_range=500.0, mpg=10.0):
    """
    O(N) greedy algorithm using a monotonic stack.
    Assumes vehicle starts with 0 fuel and buys just enough to reach the next stop.
    We need to reach 'total_distance' with 0 fuel remaining.
    """
    if total_distance <= 0:
        return [], 0.0

    # If no stations, or first station is out of reach
    if not stations:
        return None, 0.0
        
    if stations[0]['distance_along_route'] > max_range: # Wait, we assume start location has first station logic
        pass

    # We add the "End" as a dummy station at total_distance with price 0
    # so the algorithm naturally wants to reach it empty.
    dest = {
        'id': 'DEST',
        'name': 'Destination',
        'price': -1.0, # Cheapest possible, forces buying just enough to reach it
        'lat': 0, 'lng': 0,
        'distance_along_route': total_distance
    }
    
    # We add a "Start" dummy station at 0 with a very high price? 
    # The prompt user action: "Find the closest gas station to the start location... Buy exactly what you need to reach the next optimal station."
    # If the first station is at distance d1, we assume we magically start at d1 with 0 fuel?
    # Or we start at 0 with 0 fuel, but we can buy fuel at the first station for the first leg?
    # "Find the closest gas station to the start location... Buy exactly what you need... Calculate total fuel as total distance / 10."
    # The easiest way: We treat the first station in the route as our starting point, and we just add its distance to the total fuel we buy there.
    # Actually, let's just model it as starting at 0, and we buy fuel to get to the first station AT the first station's price.
    
    if stations[0]['distance_along_route'] > 0:
        # Prepend a virtual station at 0 with the same price as the first station
        start_station = stations[0].copy()
        start_station['distance_along_route'] = 0
        start_station['id'] = 'START'
        # We don't list it in the output unless we actually buy fuel there.
        # But wait, it's easier to just run the algorithm from index 0.
        pass
        
    s_list = stations + [dest]
    n = len(s_list)
    
    # Precompute next cheaper station using Monotonic Stack
    next_cheaper = [-1] * n
    stack = []
    for i in range(n):
        while stack and s_list[stack[-1]]['price'] > s_list[i]['price']:
            next_cheaper[stack.pop()] = i
        stack.append(i)
        
    current_fuel = 0.0
    current_pos = 0.0
    total_cost = 0.0
    
    # We must buy fuel to reach the first station from 0. We'll add this at the first station.
    # To handle this cleanly: Start at pos=0, fuel=0. We need to reach stations[0].
    # But wait, we can't move without fuel.
    # User said: "Find the closest gas station to the start location (or assume the start location has one). Buy exactly what you need to reach the next optimal station."
    # Let's just assume the first station is the start location (pos=0), but we use its actual coordinates for the map.
    # We'll just shift the first station to pos=0, or just let pos=0 and we magically jump to it.
    
    stops = []
    
    # Let's say we start at s_list[0].
    # We need to cover the distance from 0 to s_list[0]
    initial_deficit = s_list[0]['distance_along_route']
    if initial_deficit > max_range:
        return None, 0.0 # First station too far
        
    current_pos = s_list[0]['distance_along_route']
    # We "borrowed" fuel for initial_deficit. We must buy it at s_list[0].
    # We can just say we are at s_list[0], and our tank is actually empty, but we must buy `initial_deficit/mpg` extra gallons here.
    # Wait, the simplest way is to just assume we are at s_list[0], with 0 fuel, and we add initial_deficit to our total distance remaining.
    
    i = 0
    while i < n - 1: # don't process destination
        station = s_list[i]
        j = next_cheaper[i]
        
        # If there's a cheaper station, and it's within range
        if j != -1 and (s_list[j]['distance_along_route'] - station['distance_along_route']) <= max_range:
            # Case 1: Buy just enough to reach j
            dist_to_j = s_list[j]['distance_along_route'] - station['distance_along_route']
            fuel_needed = dist_to_j / mpg
            
            # Add the initial deficit if we are at the first station
            if i == 0:
                fuel_needed += initial_deficit / mpg
                
            fuel_to_buy = fuel_needed - current_fuel
            
            if fuel_to_buy > 0:
                cost = fuel_to_buy * station['price']
                total_cost += cost
                stops.append({
                    'station': station['name'],
                    'address': f"{station.get('lat', 0)}, {station.get('lng', 0)}", # coordinates
                    'price': station['price'],
                    'gallons': round(fuel_to_buy, 2),
                    'cost': round(cost, 2),
                    'distance': round(station['distance_along_route'], 2)
                })
                current_fuel += fuel_to_buy
                
            # Drive to j
            current_fuel -= (s_list[j]['distance_along_route'] - station['distance_along_route']) / mpg
            if i == 0:
                 current_fuel -= (initial_deficit / mpg) # subtract the borrowed amount
                 if current_fuel < -0.001: current_fuel = 0
            
            i = j
        else:
            # Case 2: No cheaper station within range.
            # Fill the tank to max capacity
            # Then find the minimum price station within range to jump to
            
            # Find next stop: minimum price station strictly within max_range
            best_next = -1
            min_p = float('inf')
            
            for k in range(i + 1, n):
                if s_list[k]['distance_along_route'] - station['distance_along_route'] > max_range:
                    break
                if s_list[k]['price'] <= min_p: # <= so we pick the furthest minimum
                    min_p = s_list[k]['price']
                    best_next = k
                    
            if best_next == -1:
                # No stations reachable!
                return None, 0.0
                
            # We are filling up, or if we can reach the end, just buy enough for the end
            if s_list[best_next]['id'] == 'DEST':
                 # We can reach the end! Just buy enough to get there
                 dist_to_end = s_list[best_next]['distance_along_route'] - station['distance_along_route']
                 fuel_needed = dist_to_end / mpg
                 if i == 0: fuel_needed += initial_deficit / mpg
                 
                 fuel_to_buy = fuel_needed - current_fuel
                 if fuel_to_buy > 0:
                     cost = fuel_to_buy * station['price']
                     total_cost += cost
                     stops.append({
                        'station': station['name'],
                        'address': f"{station.get('lat', 0)}, {station.get('lng', 0)}",
                        'price': station['price'],
                        'gallons': round(fuel_to_buy, 2),
                        'cost': round(cost, 2),
                        'distance': round(station['distance_along_route'], 2)
                     })
                 break # Reached the end
            else:
                 # Fill up
                 tank_cap = max_range / mpg
                 fuel_to_buy = tank_cap - current_fuel
                 if i == 0:
                      # If we fill up at the first station, part of that fuel goes to the initial deficit
                      # Wait, if we buy tank_cap, we have tank_cap in the tank NOW. But we owed initial_deficit.
                      # So we actually buy tank_cap + (initial_deficit/mpg). 
                      # Then our tank has tank_cap.
                      fuel_to_buy += initial_deficit / mpg
                 
                 if fuel_to_buy > 0:
                     cost = fuel_to_buy * station['price']
                     total_cost += cost
                     stops.append({
                        'station': station['name'],
                        'address': f"{station.get('lat', 0)}, {station.get('lng', 0)}",
                        'price': station['price'],
                        'gallons': round(fuel_to_buy, 2),
                        'cost': round(cost, 2),
                        'distance': round(station['distance_along_route'], 2)
                     })
                     current_fuel += fuel_to_buy
                     
                 # Drive to best_next
                 dist_to_next = s_list[best_next]['distance_along_route'] - station['distance_along_route']
                 current_fuel -= (dist_to_next / mpg)
                 if i == 0:
                     current_fuel -= (initial_deficit / mpg)
                     
                 i = best_next

    return stops, total_cost
