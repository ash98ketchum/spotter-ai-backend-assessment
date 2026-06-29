# Spotter AI Backend Assessment - Route & Fuel Optimization API

This is a high-performance Django REST API that calculates the optimal driving route between two US cities and determines the most cost-effective fuel stops along the way.

It is designed to be extremely fast and robust, heavily minimizing reliance on third-party API rate limits by utilizing advanced spatial algorithms and offline datasets.

## Architecture & Algorithms

### 1. Minimal External API Calls
To guarantee speed and prevent API throttling, the system restricts external calls:
- **OpenStreetMap Nominatim** is used strictly for geocoding the `start` and `finish` strings (2 calls).
- **OSRM (Open Source Routing Machine)** is called exactly **once** to retrieve the full, high-resolution route geometry and total distance.

### 2. $O(K \log M)$ Spatial Filtering & Snapping
The provided dataset of 8,000+ truck stops did not include coordinates, so an offline preprocessing script joins the data with a US cities dataset to approximate locations into a local SQLite database (`truck_stops.db`). 

To find which truck stops are actually on the route without an expensive $O(M \times N)$ iteration over thousands of route segments:
1. **Downsampling**: The route is downsampled to sample points every 20 miles.
2. **Spatial Radius Query**: A `scikit-learn` `BallTree` (using the Haversine metric) queries the offline dataset to quickly filter for stations within a 20-mile radius of the downsampled points.
3. **Spatial Nearest Neighbor Snapping**: A second `BallTree` is constructed from the route segments themselves, and the filtered stations query this tree to instantly snap to the closest route coordinate. This yields their exact 1D distance along the route.

### 3. $O(N)$ Monotonic Stack Optimization Algorithm
Once the filtered stations are snapped and sorted by their 1D distance along the route, the problem becomes a classic Gas Station Optimization algorithm.
- **Preprocessing**: The algorithm uses a **Monotonic Stack** to precompute the "Next Cheaper Station" in strict **$O(N)$ time complexity**.
- **Querying**: The Greedy traversal jumps between stations, making $O(1)$ lookups to decide whether to buy just enough fuel to reach a cheaper station ahead, or to fill the tank to its 500-mile capacity and jump to the minimum available price.

---

## Setup Instructions

### 1. Install Requirements
Make sure you have Python 3 installed. Run the following command to install the required dependencies:
```bash
pip install -r requirements.txt
```

### 2. Data Preprocessing (Optional, already provided)
The repository includes a preprocessed SQLite database (`truck_stops.db`). If you ever need to rebuild it, you can run the data preparation script:
```bash
python prep_data.py
```
*(This downloads a lightweight US cities dataset and merges it with the provided CSV).*

### 3. Start the Server
Start the Django development server:
```bash
python manage.py runserver
```
The server will be available at `http://127.0.0.1:8000/`.

---

## How to Test the API

You can test the API using Postman, cURL, or any web browser.

**Endpoint:**
```
GET /api/route/?start=<START_CITY>&finish=<FINISH_CITY>
```

**Example cURL:**
```bash
curl "http://127.0.0.1:8000/api/route/?start=New+York,+NY&finish=Chicago,+IL"
```

**Response Format:**
The API returns a highly detailed JSON object containing:
- `route`: The full GeoJSON `LineString` coordinate geometry returned by OSRM.
- `total_distance_miles`: The total distance of the trip.
- `total_cost`: The absolute cheapest cost to fuel the vehicle for the entire journey (assuming 10 mpg, 500-mile tank, and starting with 0 fuel).
- `fuel_stops`: An array detailing exactly where to stop, the price, the amount of gallons to buy, and the cost at that specific station.