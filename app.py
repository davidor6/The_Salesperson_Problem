import requests
import folium
import numpy as np
import polyline
import itertools
import random
import time
from flask import Flask, jsonify, request
from folium.plugins import MarkerCluster

app = Flask(__name__, static_folder='static', template_folder='templates')

class TSP:
    def __init__(self):
        self.distance_matrix = np.zeros((0, 0))
        self.routes_matrix = []
        self.map = folium.Map(location=[32.0853, 34.85], zoom_start=12)
        self.marker_cluster = MarkerCluster().add_to(self.map)
        self.nodes = []

    def geocode_address(self, address):
        nominatim_url = "https://nominatim.openstreetmap.org/search"
        headers = {
            'User-Agent': 'MyTSP/1.0 (davidor6@gmail.com)',
        }
        params = {
            'q': address,
            'format': 'json',
            'addressdetails': 1,
            'limit': 1
        }
        try:
            response = requests.get(nominatim_url, headers=headers, params=params)
            response.raise_for_status()
            results = response.json()
            if results:
                lat = float(results[0]['lat'])
                lon = float(results[0]['lon'])
                return lat, lon
        except (requests.RequestException, ValueError):
            return None

    def get_route_osrm(self, origin, destination):
        osrm_url = "http://router.project-osrm.org/route/v1/driving/"
        origin_str = f"{origin[1]},{origin[0]}"
        destination_str = f"{destination[1]},{destination[0]}"
        try:
            response = requests.get(f"{osrm_url}{origin_str};{destination_str}?overview=full")
            response.raise_for_status()
            data = response.json()
            if 'routes' in data and len(data['routes']) > 0:
                polyline_str = data['routes'][0]['geometry']
                route_coords = polyline.decode(polyline_str)
                distance = data['routes'][0]['distance'] / 1000  # Convert to kilometers
                return route_coords, distance
        except (requests.RequestException, ValueError):
            return [], 0

    def add_to_matrices(self):
        distances = []
        routes = []

        for i in range(len(self.nodes)):
            data = self.get_route_osrm(self.nodes[-1][:2], self.nodes[i][:2])
            distances.append(data[1])
            routes.append(data[0])
        distances = np.array(distances)

        self.routes_matrix.append(routes[:-1])
        for idx, route in enumerate(routes):
            if idx < len(self.routes_matrix):
                self.routes_matrix[idx].append(route)
            else:
                self.routes_matrix.append([route])
        self.distance_matrix = np.append(self.distance_matrix, [distances[:-1]], axis=0)
        self.distance_matrix = np.append(self.distance_matrix, distances.reshape(-1, 1), axis=1)

    def tsp_bruteforce(self):
        n = len(self.distance_matrix)
        permutations = itertools.permutations(range(n))
        min_cost = float('inf')
        min_path = None
        for perm in permutations:
            cost = sum(self.distance_matrix[perm[i]][perm[i + 1]] for i in range(n - 1))
            cost += self.distance_matrix[perm[-1]][perm[0]]
            if cost < min_cost:
                min_cost = cost
                min_path = perm

        return min_path, min_cost

    def nearest_neighbor(self):
        n = len(self.distance_matrix)
        visited = [False] * n
        path = [0]  # Start from the first node
        visited[0] = True
        total_cost = 0

        for _ in range(n - 1):
            last_node = path[-1]
            nearest_node = None
            min_distance = float('inf')

            for i in range(n):
                if not visited[i] and self.distance_matrix[last_node][i] < min_distance:
                    nearest_node = i
                    min_distance = self.distance_matrix[last_node][i]

            path.append(nearest_node)
            visited[nearest_node] = True
            total_cost += min_distance

        total_cost += self.distance_matrix[path[-1]][path[0]]
        return path, total_cost

    def tsp_genetic_algorithm(self, population_size=100, generations=500, mutation_rate=0.1):
        def fitness(path):
            return sum(self.distance_matrix[path[i]][path[i + 1]] for i in range(len(path) - 1)) + self.distance_matrix[path[-1]][path[0]]

        def mutate(path):
            if random.random() < mutation_rate:
                i, j = random.sample(range(len(path)), 2)
                path[i], path[j] = path[j], path[i]

        def crossover(parent1, parent2):
            size = len(parent1)
            start, end = sorted(random.sample(range(size), 2))
            child = [-1] * size
            for i in range(start, end + 1):
                child[i] = parent1[i]
            for i in range(size):
                if child[i] == -1:
                    for p in parent2:
                        if p not in child:
                            child[i] = p
                            break
            return child

        population = [random.sample(range(len(self.distance_matrix)), len(self.distance_matrix)) for _ in range(population_size)]
        for _ in range(generations):
            population.sort(key=lambda x: fitness(x))
            new_population = population[:10]  # Keep the best 10
            while len(new_population) < population_size:
                parent1, parent2 = random.sample(new_population[:10], 2)
                child = crossover(parent1, parent2)
                mutate(child)
                new_population.append(child)
            population = new_population

        best_path = min(population, key=lambda x: fitness(x))
        best_cost = fitness(best_path)
        return best_path, best_cost

tsp = TSP()

@app.route('/add_node', methods=['POST'])
def add_node():
    address = request.form.get("address")
    location = tsp.geocode_address(address)
    if location:
        tsp.nodes.append(location + (address,))
        tsp.add_to_matrices()
        folium.Marker(location, popup=f"Node {len(tsp.nodes)}: {address}").add_to(tsp.marker_cluster)
        tsp.map.save("static/map.html")
        return jsonify({"success": True, "message": f"Node added: {address}"})
    return jsonify({"success": False, "message": "Failed to geocode address."})

@app.route('/calculate_route', methods=['GET'])
def calculate_route():
    algorithm = request.args.get("algorithm")
    if len(tsp.nodes) < 2:
        return jsonify({"success": False, "message": "At least two nodes are required."})

    if algorithm == "nearest":
        path, total_cost = tsp.nearest_neighbor()
    elif algorithm == "bruteforce":
        path, total_cost = tsp.tsp_bruteforce()
    elif algorithm == "genetic":
        path, total_cost = tsp.tsp_genetic_algorithm()
    else:
        return jsonify({"success": False, "message": "Unknown algorithm."})

    route_description = []
    for i in range(len(path) - 1):
        origin = tsp.nodes[path[i]]
        destination = tsp.nodes[path[i + 1]]
        route_coords = tsp.routes_matrix[i][i + 1]
        folium.PolyLine(route_coords, color="red", weight=2.5, opacity=1).add_to(tsp.map)
        route_description.append(f"From {origin[2]} go to {destination[2]}")

    origin = tsp.nodes[path[-1]]
    destination = tsp.nodes[path[0]]
    route_coords = tsp.routes_matrix[-1][0]
    folium.PolyLine(route_coords, color="red", weight=2.5, opacity=1).add_to(tsp.map)
    route_description.append(f"From {origin[2]} go to {destination[2]}")

    tsp.map.save("static/map.html")

    route_description_str = " -> ".join(route_description)
    return jsonify({"success": True, "message": f"Route calculated: {route_description_str}", "total_cost": total_cost})

if __name__ == "__main__":
    app.run(debug=True)
