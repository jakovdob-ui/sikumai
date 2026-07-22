"""מושך Store ID ו-Variant ID מ-LemonSqueezy אוטומטית"""
import requests
import os
from dotenv import load_dotenv
load_dotenv()

API_KEY = os.getenv("LS_API_KEY")
headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Accept": "application/vnd.api+json",
}

# Store ID
r = requests.get("https://api.lemonsqueezy.com/v1/stores", headers=headers)
stores = r.json().get("data", [])
for s in stores:
    print(f"STORE: {s['attributes']['name']} → ID: {s['id']}")

# Variant ID
r2 = requests.get("https://api.lemonsqueezy.com/v1/variants", headers=headers)
variants = r2.json().get("data", [])
for v in variants:
    name = v["attributes"].get("name", "")
    price = v["attributes"].get("price", 0)
    print(f"VARIANT: {name} | price: {price} → ID: {v['id']}")
