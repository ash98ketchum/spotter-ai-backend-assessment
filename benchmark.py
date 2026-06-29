import time
import random
import statistics
import os
import django

# Setup Django environment so we can use the app's internal logic directly
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'routing_project.settings')
django.setup()

from fuel_route.routing_logic import get_route_and_stations, optimize_fuel
from unittest.mock import patch

# 15 Major US Cities with pre-geocoded coordinates to prevent Nominatim from banning us for 200 requests
CITIES = {
    "New York, NY": [-74.006, 40.7128],
    "Los Angeles, CA": [-118.2437, 34.0522],
    "Chicago, IL": [-87.6298, 41.8781],
    "Houston, TX": [-95.3698, 29.7604],
    "Phoenix, AZ": [-112.0740, 33.4484],
    "Philadelphia, PA": [-75.1652, 39.9526],
    "San Antonio, TX": [-98.4936, 29.4241],
    "San Diego, CA": [-117.1611, 32.7157],
    "Dallas, TX": [-96.7970, 32.7767],
    "San Jose, CA": [-121.8863, 37.3382],
    "Austin, TX": [-97.7431, 30.2672],
    "Jacksonville, FL": [-81.6557, 30.3322],
    "Fort Worth, TX": [-97.3208, 32.7555],
    "Columbus, OH": [-82.9988, 39.9612],
    "Charlotte, NC": [-80.8431, 35.2271]
}

def mock_geocode(location_string):
    return CITIES.get(location_string)

def run_benchmark(num_tests=100):
    print(f"Starting benchmark of {num_tests} routes...")
    print("NOTE: Geocoding is mocked to prevent Nominatim rate-limiting/bans.")
    
    city_names = list(CITIES.keys())
    
    successful_routes = 0
    failed_routes = 0
    execution_times = []
    total_costs = []
    total_distances = []
    total_gallons = []

    # Buckets for distance analysis
    distance_buckets = {
        "< 500 miles": [],
        "500 - 1000 miles": [],
        "1000 - 2000 miles": [],
        "> 2000 miles": []
    }

    # Patch the geocode function so it uses our offline dictionary
    with patch('fuel_route.routing_logic.geocode', side_effect=mock_geocode):
        for i in range(num_tests):
            # Pick 2 different random cities
            start, finish = random.sample(city_names, 2)
            
            start_time = time.time()
            
            # Run the logic
            try:
                res = get_route_and_stations(start, finish)
                if res[0] is None:
                    failed_routes += 1
                    continue
                    
                geometry, stations, dist = res
                stops, cost = optimize_fuel(stations, dist)
                
                if stops is None:
                    failed_routes += 1
                    continue
                    
                end_time = time.time()
                
                # Record metrics
                exec_time = end_time - start_time
                execution_times.append(exec_time)
                successful_routes += 1
                total_costs.append(cost)
                total_distances.append(dist)
                
                gallons = sum(s['gallons'] for s in stops)
                total_gallons.append(gallons)
                
                # Assign to bucket
                if dist < 500:
                    distance_buckets["< 500 miles"].append(exec_time)
                elif dist < 1000:
                    distance_buckets["500 - 1000 miles"].append(exec_time)
                elif dist < 2000:
                    distance_buckets["1000 - 2000 miles"].append(exec_time)
                else:
                    distance_buckets["> 2000 miles"].append(exec_time)
                
                # Print progress every 10 runs
                if (i + 1) % 10 == 0:
                    print(f"[{i + 1}/{num_tests}] Processed {start} -> {finish} ({dist:.1f} mi) in {exec_time:.3f}s")
                    
            except Exception as e:
                print(f"Error on {start} -> {finish}: {e}")
                failed_routes += 1
                
            # Sleep briefly to not overwhelm the OSRM public API
            time.sleep(0.5)

    print("\n" + "="*45)
    print("BENCHMARK RESULTS")
    print("="*45)
    print(f"Total Routes Tested: {num_tests}")
    print(f"Successful Routes:   {successful_routes}")
    print(f"Failed/Impossible:   {failed_routes}")
    print("-" * 45)
    
    if execution_times:
        print(f"Average Speed:       {statistics.mean(execution_times):.3f} seconds / route")
        print(f"Median Speed:        {statistics.median(execution_times):.3f} seconds / route")
        print(f"Min Speed:           {min(execution_times):.3f} seconds")
        print(f"Max Speed:           {max(execution_times):.3f} seconds")
        print("-" * 45)
        
        print("AVERAGE PROCESSING TIME BY DISTANCE BUCKET:")
        for bucket, times in distance_buckets.items():
            if times:
                avg_t = statistics.mean(times)
                print(f"  {bucket.ljust(18)}: {avg_t:.3f}s (n={len(times)})")
            else:
                print(f"  {bucket.ljust(18)}: No routes in this range")
        
        print("-" * 45)
        # Accuracy checks
        mpg_accuracies = [(g * 10) / d if d > 0 else 1 for g, d in zip(total_gallons, total_distances)]
        avg_accuracy = statistics.mean(mpg_accuracies) * 100
        print(f"MPG/Distance Match:  {avg_accuracy:.2f}% accuracy")
        
    else:
        print("No successful routes to calculate stats.")

if __name__ == '__main__':
    run_benchmark(100)
