import os
import time
import geopandas as gpd
import pandas as pd
import osmnx as ox

# 1. Configure OSMnx caching and higher timeout
ox.settings.use_cache = True
ox.settings.cache_folder = "./osm_cache"
ox.settings.requests_timeout = 300  # Give large cities like Rome 5 minutes
ox.settings.overpass_rate_limit = True

# List of public Overpass API mirrors to fall back on if the main one returns 502/504
OVERPASS_ENDPOINTS = [
    "https://overpass.private.coffee/api",   # Fast, generous limits
    "https://maps.mail.ru/osm/tools/overpass/api",  # High-capacity mirror
    "https://overpass-api.de/api",           # Default main server
]

os.makedirs("data/external", exist_ok=True)

CITIES = {
    # "Milano": {
    #     "query": "Milano, Lombardia, Italy",
    #     "epsg": 32632,
    # },
    "Roma": {
        "query": "Roma, Lazio, Italy",
        "epsg": 32633,
    },
}

OSM_TAGS = {
    "metro": {"railway": ["station", "subway_entrance"]},
    "public_transit": {"highway": ["bus_stop"], "railway": ["tram_stop"]},
    "parks": {"leisure": ["park", "garden"]},
    "supermarkets": {"shop": ["supermarket", "convenience"]},
    "monuments": {
        "historic": ["monument", "memorial", "castle", "ruins", "archaeological_site"],
        "tourism": ["attraction", "museum"],
    },
    "food_nightlife": {"amenity": ["restaurant", "bar", "cafe"]},
}

def query_with_retries(place_query: str, tags: dict, max_retries: int = 4) -> gpd.GeoDataFrame:
    """Queries OSMnx with exponential backoff and automatic mirror rotation."""
    wait_seconds = 5
    for attempt in range(max_retries):
        # Rotate through mirrors on each attempt
        endpoint = OVERPASS_ENDPOINTS[attempt % len(OVERPASS_ENDPOINTS)]
        ox.settings.overpass_url = endpoint
        try:
            print(f"  [Attempt {attempt + 1}] Using server: {endpoint} ...")
            return ox.features_from_place(place_query, tags=tags)
        except Exception as e:
            print(f"  Warning: Server busy ({e}). Waiting {wait_seconds}s before retry...")
            time.sleep(wait_seconds)
            wait_seconds *= 2  # Exponential backoff (5s -> 10s -> 20s -> 40s)

    raise RuntimeError(f"Failed to fetch data for {place_query} after {max_retries} retries.")

def fetch_city_pois(city_name: str, config: dict):
    print(f"\n=== Fetching OpenStreetMap data for {city_name} ===")
    epsg = config["epsg"]
    place_query = config["query"]
    out_path = f"data/external/{city_name.lower()}_pois.gpkg"

    for category, tags in OSM_TAGS.items():
        # Check if layer already exists so it can resume if interrupted
        if os.path.exists(out_path):
            try:
                existing = gpd.read_file(out_path, layer=category)
                if len(existing) > 0:
                    print(f"Skipping '{category}' (already saved with {len(existing)} points).")
                    continue
            except Exception:
                pass

        print(f"Fetching '{category}'...")
        gdf = query_with_retries(place_query, tags)

        cols_to_keep = [c for c in ["name", "geometry"] if c in gdf.columns]
        gdf = gdf[cols_to_keep].copy().reset_index(drop=True)

        # Project to local meters and convert shapes to center points
        gdf_metric = gdf.to_crs(epsg=epsg)
        gdf_metric["geometry"] = gdf_metric.geometry.centroid

        gdf_metric.to_file(out_path, layer=category, driver="GPKG")
        print(f"  -> Saved {len(gdf_metric)} '{category}' points to {out_path}")

        # Pause between categories
        time.sleep(3)

for city, cfg in CITIES.items():
  fetch_city_pois(city, cfg)
