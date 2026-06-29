from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .routing_logic import get_route_and_stations, optimize_fuel

class RouteView(APIView):
    def get(self, request):
        start = request.query_params.get('start')
        finish = request.query_params.get('finish')
        
        if not start or not finish:
            return Response({"error": "Please provide 'start' and 'finish' locations."}, status=status.HTTP_400_BAD_REQUEST)
            
        geometry, stations, total_distance = get_route_and_stations(start, finish)
        
        if geometry is None:
            return Response(stations, status=status.HTTP_400_BAD_REQUEST)
            
        stops, total_cost = optimize_fuel(stations, total_distance)
        
        if stops is None:
            return Response({"error": "Route is impossible to complete with the given 500 mile range."}, status=status.HTTP_400_BAD_REQUEST)
            
        return Response({
            "route": geometry,
            "total_distance_miles": round(total_distance, 2),
            "total_cost": round(total_cost, 2),
            "fuel_stops": stops
        }, status=status.HTTP_200_OK)
