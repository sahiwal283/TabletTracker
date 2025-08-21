import time
import base64
from typing import Optional, Dict, Any
import requests
from datetime import datetime
from config import Config


class UPSTrackingClient:
    """Minimal UPS OAuth2 + Tracking API client."""

    def __init__(self):
        self.base = Config.UPS_API_BASE.rstrip('/')
        self.client_id = Config.UPS_CLIENT_ID
        self.client_secret = Config.UPS_CLIENT_SECRET
        self._token: Optional[str] = None
        self._token_expiry: float = 0

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token

        token_url = f"{self.base}/security/v1/oauth/token"
        data = {"grant_type": "client_credentials"}
        auth = (self.client_id, self.client_secret)
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        resp = requests.post(token_url, data=data, auth=auth, headers=headers, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        self._token = payload.get("access_token")
        expires_in = payload.get("expires_in", 3300)
        self._token_expiry = time.time() + int(expires_in)
        return self._token

    def track(self, tracking_number: str) -> Dict[str, Any]:
        token = self._get_token()
        url = f"{self.base}/api/track/v1/details/{tracking_number}"
        headers = {
            "Authorization": f"Bearer {token}",
            "transId": str(int(time.time() * 1000)),
            "transactionSrc": Config.UPS_TRANSACTION_SRC or "TabletTracker",
        }
        resp = requests.get(url, headers=headers, timeout=20)
        # UPS returns 200 on found; 404 for unknown
        if resp.status_code == 404:
            return {"status": "Unknown", "raw": resp.text}
        resp.raise_for_status()
        data = resp.json()
        return data


def normalize_ups_response(data: Dict[str, Any]) -> Dict[str, Any]:
    """Map UPS response to our unified schema."""
    status_text = "Unknown"
    est_delivery = None
    delivered_at = None
    last_checkpoint = None

    try:
        shipment = data.get("trackResponse", {}).get("shipment", [{}])[0]
        activities = shipment.get("package", [{}])[0].get("activity", [])
        if activities:
            last = activities[0]
            desc = last.get("status", {}).get("description") or last.get("statusCode")
            status_text = desc or status_text
            date = last.get("date")
            time_str = last.get("time")
            if date and time_str:
                last_checkpoint = f"{date} {time_str}"

        # Delivery details
        delivery = shipment.get("package", [{}])[0].get("deliveryDate", [])
        if delivery:
            est_delivery = delivery[0].get("date")

        # Delivered check
        current_status = shipment.get("currentStatus", {}).get("description")
        if current_status and "delivered" in current_status.lower():
            delivered_at = shipment.get("deliveryDetails", {}).get("date")

    except Exception:
        pass

    return {
        "tracking_status": status_text,
        "estimated_delivery": est_delivery,
        "delivered_at": delivered_at,
        "last_checkpoint": last_checkpoint,
        "provider_raw": data,
    }


class FedExTrackingClient:
    """Minimal FedEx OAuth2 + Tracking API client."""

    def __init__(self):
        self.base = (Config.FEDEX_BASE or 'https://apis.fedex.com').rstrip('/')
        self.api_key = Config.FEDEX_API_KEY
        self.api_secret = Config.FEDEX_API_SECRET
        self.account = Config.FEDEX_ACCOUNT_NUMBER
        self._token: Optional[str] = None
        self._token_expiry: float = 0

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        url = f"{self.base}/oauth/token"
        data = {"grant_type": "client_credentials"}
        auth = (self.api_key, self.api_secret)
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        resp = requests.post(url, data=data, auth=auth, headers=headers, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        self._token = payload.get("access_token")
        expires_in = payload.get("expires_in", 3300)
        self._token_expiry = time.time() + int(expires_in)
        return self._token

    def track(self, tracking_number: str) -> Dict[str, Any]:
        token = self._get_token()
        url = f"{self.base}/track/v1/trackingnumbers"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        body = {
            "trackingInfo": [{"trackingNumberInfo": {"trackingNumber": tracking_number}}],
            "includeDetailedScans": True,
        }
        resp = requests.post(url, headers=headers, json=body, timeout=20)
        if resp.status_code == 404:
            return {"status": "Unknown", "raw": resp.text}
        resp.raise_for_status()
        return resp.json()


def normalize_fedex_response(data: Dict[str, Any]) -> Dict[str, Any]:
    status_text = "Unknown"
    est_delivery = None
    delivered_at = None
    last_checkpoint = None
    try:
        shipments = data.get("output", {}).get("completeTrackResults", [])
        if shipments:
            result = shipments[0].get("trackResults", [{}])[0]
            status_text = result.get("latestStatusDetail", {}).get("statusByLocale") or status_text
            est = result.get("dateAndTimes", [])
            for dt in est:
                if dt.get("type") == "ESTIMATED_DELIVERY":
                    est_delivery = dt.get("dateTime")
                    break
            scans = result.get("scanEvents", [])
            if scans:
                last_checkpoint = scans[0].get("date")
            if (result.get("latestStatusDetail", {}).get("code") or "").lower() == "dlv":
                delivered_at = result.get("dateAndTimes", [{}])[0].get("dateTime")
    except Exception:
        pass

    return {
        "tracking_status": status_text,
        "estimated_delivery": est_delivery,
        "delivered_at": delivered_at,
        "last_checkpoint": last_checkpoint,
        "provider_raw": data,
    }


def refresh_shipment_row(conn, shipment_id: int) -> Dict[str, Any]:
    """Fetch shipment, call provider, and persist results."""
    cur = conn.cursor()
    row = cur.execute(
        "SELECT id, tracking_number, carrier, carrier_code FROM shipments WHERE id = ?",
        (shipment_id,),
    ).fetchone()
    if not row:
        return {"success": False, "error": "Shipment not found"}

    tracking_number = row[1]
    carrier = (row[2] or "").lower()
    carrier_code = (row[3] or "").lower()

    # Currently support UPS and FedEx
    if carrier in ("ups",) or carrier_code in ("ups", "ups_ground", "ups_air"):
        client = UPSTrackingClient()
        raw = client.track(tracking_number)
        norm = normalize_ups_response(raw)
    elif carrier in ("fedex", "fed ex", "fx") or carrier_code in ("fedex", "fx"):
        client = FedExTrackingClient()
        raw = client.track(tracking_number)
        norm = normalize_fedex_response(raw)
    else:
        return {"success": False, "error": f"Carrier not supported: {carrier or carrier_code}"}

    cur.execute(
        """
        UPDATE shipments SET 
            tracking_status = ?, 
            estimated_delivery = COALESCE(?, estimated_delivery),
            delivered_at = COALESCE(?, delivered_at),
            last_checkpoint = ?,
            last_checked_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            norm.get("tracking_status"),
            norm.get("estimated_delivery"),
            norm.get("delivered_at"),
            norm.get("last_checkpoint"),
            shipment_id,
        ),
    )
    conn.commit()

    return {"success": True, "shipment_id": shipment_id, "data": norm}

