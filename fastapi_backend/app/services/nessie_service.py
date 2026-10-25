"""Client for the Capital One Nessie mock banking API (http://api.nessieisreal.com)."""

import asyncio
from typing import Any

import httpx

from app.config import settings

# Starting balance for the mock checking account created for each new user.
DEMO_CHECKING_BALANCE = 1250.00


class NessieError(Exception):
    pass


RETRY_DELAYS_S = (1, 3)


async def _request(method: str, path: str, json: dict | None = None) -> Any:
    """One Nessie call. Timeouts, 429s and 5xx errors are retried twice."""
    if not settings.NESSIE_API_KEY:
        raise NessieError("NESSIE_API_KEY is not set")

    async with httpx.AsyncClient(
        base_url=settings.NESSIE_BASE_URL, timeout=15
    ) as client:
        for attempt in range(len(RETRY_DELAYS_S) + 1):
            try:
                response = await client.request(
                    method, path, params={"key": settings.NESSIE_API_KEY}, json=json
                )
            except httpx.TransportError as exc:
                problem = type(exc).__name__
            else:
                if response.status_code < 400:
                    return response.json()
                problem = f"HTTP {response.status_code}"
                if response.status_code != 429 and response.status_code < 500:
                    break  # a bad request won't succeed on retry
            if attempt < len(RETRY_DELAYS_S):
                await asyncio.sleep(RETRY_DELAYS_S[attempt])
        raise NessieError(f"Nessie request failed: {method} {path} ({problem})")


async def create_demo_customer(first_name: str, last_name: str, zip_code: str) -> str:
    """Create a Nessie customer with one checking account; return the customer id."""
    customer = await _request(
        "POST",
        "/customers",
        json={
            "first_name": first_name,
            "last_name": last_name,
            "address": {
                "street_number": "2317",
                "street_name": "Speedway",
                "city": "Austin",
                "state": "TX",
                "zip": zip_code,
            },
        },
    )
    customer_id: str = customer["objectCreated"]["_id"]

    await _request(
        "POST",
        f"/customers/{customer_id}/accounts",
        json={
            "type": "Checking",
            "nickname": "Everyday Checking",
            "rewards": 0,
            "balance": DEMO_CHECKING_BALANCE,
        },
    )
    return customer_id


async def get_account_balance(account_id: str) -> float:
    account = await _request("GET", f"/accounts/{account_id}")
    return float(account["balance"])


async def get_checking_balance(customer_id: str) -> float:
    """Total balance across the customer's checking accounts."""
    accounts = await _request("GET", f"/customers/{customer_id}/accounts")
    return float(sum(a["balance"] for a in accounts if a.get("type") == "Checking"))


# --- Transaction history (used by app.finance) --------------------------------

ACCOUNT_RESOURCES = ("purchases", "deposits", "bills", "loans", "withdrawals")


async def checking_account_ids(customer_id: str) -> list[str]:
    accounts = await _request("GET", f"/customers/{customer_id}/accounts")
    return [a["_id"] for a in accounts if a.get("type") == "Checking"]


async def list_account_resource(account_id: str, resource: str) -> list[dict[str, Any]]:
    """GET /accounts/{id}/{resource}. Nessie returns a message string when empty."""
    data = await _request("GET", f"/accounts/{account_id}/{resource}")
    return data if isinstance(data, list) else []


async def create_account_resource(
    account_id: str, resource: str, body: dict[str, Any]
) -> str:
    created = await _request("POST", f"/accounts/{account_id}/{resource}", json=body)
    return str(created["objectCreated"]["_id"])


async def get_merchant(merchant_id: str) -> dict[str, Any]:
    data = await _request("GET", f"/merchants/{merchant_id}")
    return data if isinstance(data, dict) else {}


async def create_merchant(name: str, category: str) -> str:
    """Nessie wants category as a single string and a full address + geocode."""
    created = await _request(
        "POST",
        "/merchants",
        json={
            "name": name,
            "category": category,
            "address": {
                "street_number": "1",
                "street_name": "Main St",
                "city": "Austin",
                "state": "TX",
                "zip": "78701",
            },
            "geocode": {"lat": 30.2672, "lng": -97.7431},
        },
    )
    return str(created["objectCreated"]["_id"])
