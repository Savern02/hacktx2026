"""Client for the Capital One Nessie mock banking API (http://api.nessieisreal.com)."""

from typing import Any

import httpx

from app.config import settings

# Starting balance for the mock checking account created for each new user.
DEMO_CHECKING_BALANCE = 1250.00


class NessieError(Exception):
    pass


async def _request(method: str, path: str, json: dict | None = None) -> Any:
    if not settings.NESSIE_API_KEY:
        raise NessieError("NESSIE_API_KEY is not set")

    async with httpx.AsyncClient(
        base_url=settings.NESSIE_BASE_URL, timeout=10
    ) as client:
        try:
            response = await client.request(
                method, path, params={"key": settings.NESSIE_API_KEY}, json=json
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise NessieError(f"Nessie request failed: {method} {path}") from exc
        return response.json()


async def create_demo_customer(first_name: str, last_name: str) -> str:
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
                "zip": "78712",
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
