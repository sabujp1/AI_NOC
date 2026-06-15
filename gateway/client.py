import httpx
from gateway.config import settings

class LibreNMSClient:
    def __init__(self):
        self.base_url = settings.LIBRENMS_API_URL.rstrip('/')
        self.headers = {
            "X-Auth-Token": settings.LIBRENMS_API_TOKEN,
            "Accept": "application/json"
        }

    async def get_devices(self):
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.base_url}/devices", headers=self.headers)
            response.raise_for_status()
            return response.json()

    async def get_alerts(self):
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.base_url}/alerts", headers=self.headers)
            response.raise_for_status()
            return response.json()

    async def get_bgp_sessions(self):
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.base_url}/bgp", headers=self.headers)
            response.raise_for_status()
            return response.json()

librenms_client = LibreNMSClient()
