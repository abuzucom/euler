import requests

BASE = "https://payments.staging.internal.acme-corp.net/v2"


def create_charge(amount):
    return requests.post(f"{BASE}/charges", json={"amount": amount}, timeout=10).json()
