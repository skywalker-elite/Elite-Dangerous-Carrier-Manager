from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import webbrowser
import re
from typing import Any, Dict, Optional
from dotenv import load_dotenv
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Callable, Literal, Optional

import jwt
from jwt import PyJWKClient, InvalidTokenError
import keyring
import requests

from config import LOCAL_PORT, REDIRECT_URL_CAPI
from utility import rate_limited

# =========
# Constants
# =========

load_dotenv()  # load .env file if present
# Your Next.js dashboard domain hosting /api/auth/exchange and /api/auth/refresh
AUTH_SERVER = os.getenv(
    "AUTH_SERVER",
    "https://auth.frontierstore.net",
)

# Discord application (reads from env, falls back to your current ID)
CAPI_CLIENT_ID = os.getenv("CAPI_CLIENT_ID", "")

# Scopes: external login only asks for `identify` (no email); PTN flow can add `guilds.members.read`.
BASE_SCOPES = "auth capi"

KEYRING_SERVICE = "edcm"
KEYRING_ACCOUNT = "refresh_token_capi"
KEYRING_ACCOUNT_PREFIX = "refresh_token_capi::"
KEYRING_ACCOUNT_INDEX = "refresh_token_capi::accounts"

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
SNOWFLAKE_RE = re.compile(r"^\d{17,20}$")

class JwtVerifier:
    def __init__(self, supabase_url: str):
        self.issuer = f"{supabase_url}/auth/v1"
        self.audience = "authenticated"
        self.jwks_url = f"{self.issuer}/.well-known/jwks.json"
        self._client = PyJWKClient(self.jwks_url, cache_keys=True)

    def decode_verify(self, token: str) -> dict:
        """
        Verifies signature, exp/nbf, issuer and audience.
        Supports ES256 and RS256 keys in the project JWKS.
        """
        try:
            # Fast path (uses 'kid' if present)
            signing_key = self._client.get_signing_key_from_jwt(token).key
            return jwt.decode(
                token,
                signing_key,
                algorithms=["ES256", "RS256"],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iss", "aud", "sub"]},
                leeway=30,
            )
        except Exception as e:
            # Fallback: handle tokens without 'kid' by trying all keys
            try:
                jwks = requests.get(self.jwks_url, timeout=5).json().get("keys", [])
                for jwk in jwks:
                    try:
                        key = jwt.PyJWK.from_dict(jwk).key
                        return jwt.decode(
                            token,
                            key,
                            algorithms=["ES256", "RS256"],
                            audience=self.audience,
                            issuer=self.issuer,
                            options={"require": ["exp", "iss", "aud", "sub"]},
                            leeway=30,
                        )
                    except Exception:
                        pass
            except Exception:
                pass
            raise e

# ----------------
# Utility helpers
# ----------------

def _post_json(url_path: str, payload: dict, timeout: int = 20) -> dict:
    url = f"{AUTH_SERVER}{url_path}"
    headers = { "Content-Type": "application/x-www-form-urlencoded" }
    r = requests.post(url, data=payload, headers=headers, timeout=timeout)
    if r.status_code >= 400:
        print("POST", url, "->", r.status_code, "\n", r.text)
        r.raise_for_status()
    return r.json()

def _get_capi(path: str, auth_header: dict, timeout: int = 20) -> requests.Response:
    url = f"https://companion.orerve.net{path}"
    return requests.get(url, headers=auth_header, timeout=timeout)

def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(os.urandom(32)).decode()#.rstrip("=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    return verifier, challenge

def _capi_auth_url(scopes: str, code_challenge: str, state: str) -> str:
    f"https://auth.frontierstore.net/auth?audience=frontier&scope=auth%20capi&response_type=code&client_id={CAPI_CLIENT_ID}&code_challenge={code_challenge}&code_challenge_method=S256&state={state}&redirect_uri={REDIRECT_URL_CAPI}"
    params = {
        "audience": "frontier",
        "client_id": CAPI_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URL_CAPI, 
        "scope": scopes,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    return requests.Request("GET", "https://auth.frontierstore.net/auth", params=params).prepare().url

def _b64pad(s: str) -> str:
    return s + "=" * (-len(s) % 4)

def _is_uuid(s: str | None) -> bool:
    return bool(s and UUID_RE.match(s))

def _is_snowflake(s: str | None) -> bool:
    return bool(s and SNOWFLAKE_RE.match(s))

def _decode_hex_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    raw = value.strip()
    if not raw:
        return ""
    hex_text = raw[2:] if raw.lower().startswith("0x") else raw
    if len(hex_text) % 2 != 0 or not re.fullmatch(r"[0-9a-fA-F]+", hex_text):
        return raw
    try:
        return bytes.fromhex(hex_text).decode("utf-8", errors="replace").rstrip("\x00")
    except Exception:
        return raw

def _normalize_callsign(callsign: str | None) -> str | None:
    if callsign is None:
        return None
    normalized = re.sub(r"\s+", "", callsign.strip().upper())
    if not normalized:
        return None
    if not re.fullmatch(r"[A-Z0-9]{3}-[A-Z0-9]{3}", normalized):
        raise ValueError(f"Invalid carrier callsign format: {callsign}")
    return normalized

# -----------------------------------
# Local callback server (PKCE flows)
# -----------------------------------

class _CallbackHandler(BaseHTTPRequestHandler):
    # populated at runtime
    result: Dict[str, Any] = {"code": None, "state": None, "error": None}
    render_html: Callable[[str, str, list[str]], bytes] = lambda *args, **kwargs: b""

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        try:
            q = parse_qs(urlparse(self.path).query)
            if "error" in q:
                _CallbackHandler.result = {"error": q.get("error", ["unknown"])[0]}
                self._send(400, _CallbackHandler.render_html(
                    "Authentication Failed", "Authentication failed!",
                    [f"<em>Error:</em> {_CallbackHandler.result['error']}"]
                ))
                return
            code = q.get("code", [None])[0]
            state = q.get("state", [None])[0]
            _CallbackHandler.result = {"code": code, "state": state}
            self._send(200, _CallbackHandler.render_html(
                "Authentication Successful", "Authentication successful!",
                ["You can close this window and return to EDCM."]
            ))
        except Exception as e:
            self._send(500, _CallbackHandler.render_html(
                "Authentication Failed", "Authentication failed!",
                [f"<em>Error:</em> {e}"]
            ))

    def log_message(self, fmt, *args):  # silence
        return

    def _send(self, status: int, body: bytes):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

def _run_callback_server(render_html: Callable[[str, str, list[str]], bytes], timeout_sec: int = 300):
    _CallbackHandler.result = {"code": None, "state": None, "error": None}
    _CallbackHandler.render_html = render_html
    httpd = HTTPServer(("127.0.0.1", LOCAL_PORT), _CallbackHandler)
    httpd.timeout = timeout_sec
    end_at = time.time() + timeout_sec
    while (
        _CallbackHandler.result["code"] is None
        and _CallbackHandler.result["error"] is None
        and time.time() < end_at
    ):
        httpd.handle_request()
    httpd.server_close()

# ---------------
# Auth Handler
# ---------------

class AuthHandler:
    """
    - Normal login uses external PKCE OAuth (identify only); stores refresh token in keyring.
    - PTN verification uses a one-off user OAuth (identify + guilds.members.read); no Supabase Auth.
    - All Supabase calls use our custom access JWT for RLS.
    """

    def __init__(self, callsign: str | None = None, auto_restore: bool = True):
        self._account_callsign: str | None = _normalize_callsign(callsign)
        self._refresh_keyring_account = self._keyring_account_for_callsign(self._account_callsign)
        self._access_jwt: Optional[str] = None
        self._token_type: str = "Bearer"
        self._access_exp: float = 0.0
        self._jwt_verifier = JwtVerifier(AUTH_SERVER)
        self._claims: Dict[str, Any] = {}

        # Simple event bus
        self._auth_event_callbacks: dict[str, list[Callable[[], None]]] = {
            "SIGNED_IN": [], "SIGNED_OUT": []
        }

        # Try to restore session (silent)
        if auto_restore:
            self._restore_from_refresh()

    @classmethod
    def _keyring_account_for_callsign(cls, callsign: str | None) -> str:
        normalized = _normalize_callsign(callsign)
        return f"{KEYRING_ACCOUNT_PREFIX}{normalized}" if normalized else KEYRING_ACCOUNT

    @classmethod
    def _load_callsign_index(cls) -> list[str]:
        try:
            raw = keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT_INDEX)
        except Exception:
            return []
        if not raw:
            return []
        try:
            values = json.loads(raw)
            if not isinstance(values, list):
                return []
            callsigns: list[str] = []
            for value in values:
                if isinstance(value, str):
                    try:
                        normalized = _normalize_callsign(value)
                    except ValueError:
                        continue
                    if normalized:
                        callsigns.append(normalized)
            return sorted(set(callsigns))
        except Exception:
            return []

    @classmethod
    def _save_callsign_index(cls, callsigns: list[str]) -> None:
        normalized_values: set[str] = set()
        for value in callsigns:
            if not isinstance(value, str):
                continue
            try:
                normalized = _normalize_callsign(value)
            except ValueError:
                continue
            if normalized:
                normalized_values.add(normalized)
        normalized = sorted(normalized_values)
        keyring.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT_INDEX, json.dumps(normalized))

    @classmethod
    def _remember_callsign(cls, callsign: str) -> None:
        normalized = _normalize_callsign(callsign)
        if not normalized:
            return
        current = cls._load_callsign_index()
        if normalized not in current:
            current.append(normalized)
            cls._save_callsign_index(current)

    @classmethod
    def _forget_callsign(cls, callsign: str) -> None:
        normalized = _normalize_callsign(callsign)
        if not normalized:
            return
        current = [value for value in cls._load_callsign_index() if value != normalized]
        cls._save_callsign_index(current)

    @classmethod
    def list_saved_callsigns(cls) -> list[str]:
        return cls._load_callsign_index()

    @classmethod
    def remove_saved_account(cls, callsign: str) -> None:
        normalized = _normalize_callsign(callsign)
        if not normalized:
            return
        try:
            keyring.delete_password(KEYRING_SERVICE, cls._keyring_account_for_callsign(normalized))
        except Exception:
            pass
        cls._forget_callsign(normalized)

    # ---- Event API ----
    def register_auth_event_callback(self, event: str, cb: Callable[[], None]) -> None:
        if event not in self._auth_event_callbacks:
            raise ValueError(f"Unknown auth event: {event}")
        self._auth_event_callbacks[event].append(cb)

    def unregister_auth_event_callback(self, event: str, cb: Callable[[], None]) -> None:
        if event in self._auth_event_callbacks and cb in self._auth_event_callbacks[event]:
            self._auth_event_callbacks[event].remove(cb)

    def _emit(self, event: str) -> None:
        for cb in list(self._auth_event_callbacks.get(event, [])):
            try:
                cb()
            except Exception as e:
                print(f"[auth] callback error for {event}: {e}")

    # ---- HTML (kept style) ----
    def _render_page(self, title: str, heading: str, messages: list[str]) -> bytes:
        msgs = "".join(f"<p>{m}</p>" for m in messages)
        html = f"""<!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="utf-8">
            <title>{title}</title>
            <link rel="icon" type="image/x-icon" href="https://raw.githubusercontent.com/skywalker-elite/Elite-Dangerous-Carrier-Manager/main/images/EDCM.ico"/>
            <style>
                body {{
                    margin: 0;
                    padding: 50px;
                    background-color: #121212;
                    color: #eee;
                    font-family: sans-serif;
                    text-align: center;
                }}
                img {{
                    display: block;
                    margin: 20px auto;
                }}
            </style>
        </head>
        <body>
            <h2>Elite Dangerous Carrier Manager</h2>
            <img
                src="https://raw.githubusercontent.com/skywalker-elite/Elite-Dangerous-Carrier-Manager/main/images/EDCM.png"
                width="128" height="128"/>
            <h1>{heading}</h1>
            {msgs}
        </body>
        </html>"""
        return html.encode("utf-8")

    def _store_refresh_to_account(self, keyring_account: str, token: str):
        keyring.set_password(KEYRING_SERVICE, keyring_account, token)

    def _load_refresh_from_account(self, keyring_account: str) -> Optional[str]:
        try:
            return keyring.get_password(KEYRING_SERVICE, keyring_account)
        except Exception:
            return None

    def _clear_refresh_from_account(self, keyring_account: str):
        try:
            keyring.delete_password(KEYRING_SERVICE, keyring_account)
        except Exception:
            pass

    def _store_refresh(self, token: str):
        self._store_refresh_to_account(self._refresh_keyring_account, token)
        if self._account_callsign:
            self._remember_callsign(self._account_callsign)

    def _load_refresh(self) -> Optional[str]:
        return self._load_refresh_from_account(self._refresh_keyring_account)

    def _clear_refresh(self):
        self._clear_refresh_from_account(self._refresh_keyring_account)

    def _set_account_callsign(self, callsign: str | None) -> None:
        normalized = _normalize_callsign(callsign)
        if not normalized:
            return

        old_account = self._refresh_keyring_account
        new_account = self._keyring_account_for_callsign(normalized)

        if old_account == KEYRING_ACCOUNT and old_account != new_account:
            legacy_token = self._load_refresh_from_account(old_account)
            if legacy_token:
                self._store_refresh_to_account(new_account, legacy_token)
                self._clear_refresh_from_account(old_account)

        self._account_callsign = normalized
        self._refresh_keyring_account = new_account
        self._remember_callsign(normalized)

    def _resolve_account_callsign_from_fleetcarrier(self, timeout: int = 20) -> None:
        try:
            status = self.get_fleetcarrier_status(timeout=timeout)
            if status.get("status_code") == 200 and status.get("found"):
                summary = self.get_fleetcarrier_summary(timeout=timeout)
                callsign = summary.get("callsign") if isinstance(summary, dict) else None
                if isinstance(callsign, str):
                    self._set_account_callsign(callsign)
        except Exception:
            pass

    def _apply_token_response(self, data: dict):
        access_token = data.get("access_token") or data.get("access_jwt")
        if not access_token:
            raise KeyError("Token response missing 'access_token'")

        self._access_jwt = access_token
        self._token_type = str(data.get("token_type") or "Bearer")

        expires_in = data.get("expires_in")
        if expires_in is not None:
            self._access_exp = time.time() + float(expires_in)
        else:
            try:
                claims = jwt.decode(
                    access_token,
                    options={"verify_signature": False, "verify_exp": False},
                )
                self._access_exp = float(claims.get("exp", 0))
            except Exception:
                self._access_exp = time.time() + 3600

        refresh_token = data.get("refresh_token")
        if refresh_token:
            self._store_refresh(refresh_token)

    def _need_refresh(self) -> bool:
        return (self._access_jwt is None) or (time.time() >= self._access_exp - 30)
    
    def _auth_header(self) -> dict:
        return {"Authorization": f"{self._token_type} {self._access_jwt}"} if self._access_jwt else {}

    @staticmethod
    def _as_dict_list(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            return [item for item in value.values() if isinstance(item, dict)]
        return []

    def _get_authenticated_header(self) -> dict[str, str]:
        if not self.is_logged_in() or not self._access_jwt:
            raise RuntimeError("No access token available")
        return self._auth_header()

    # ---- External login (identify only) ----
    def login(self) -> bool:
        verifier, challenge = _pkce_pair()
        state = secrets.token_urlsafe(24)

        # Start local callback server loop
        t = threading.Thread(target=_run_callback_server, args=(self._render_page,), daemon=True)
        t.start()

        # Authorize in browser
        url = _capi_auth_url(BASE_SCOPES, challenge, state)
        print(url)
        print("Your browser has been opened to sign in with Frontier.")
        webbrowser.open(url)

        # Wait for server to capture callback
        t.join()

        result = _CallbackHandler.result
        if result.get("error"):
            raise RuntimeError(f"OAuth error: {result['error']}")
        if not result.get("code"):
            raise RuntimeError("Timeout waiting for OAuth callback")
        if result.get("state") != state:
            raise RuntimeError("State mismatch during OAuth")

        # Exchange on Frontier: returns { access_token, refresh_token, token_type, expires_in }
        print("Exchanging authorization code for access token...")
        print(f'Received code: {result["code"]}, state: {result["state"]}, verifier: {verifier}')
        data = _post_json(
            "/token",
            {
                "redirect_uri": REDIRECT_URL_CAPI,
                "code": result["code"],
                "grant_type": "authorization_code",
                "code_verifier": verifier,
                "client_id": CAPI_CLIENT_ID,
            },
            timeout=20,
        )
        print(data)
        self._apply_token_response(data)
        self._resolve_account_callsign_from_fleetcarrier(timeout=20)
        self._emit("SIGNED_IN")
        return True

    def _refresh_access(self) -> bool:
        rt = self._load_refresh()
        if not rt:
            return False
        try:
            data = _post_json(
                "/token",
                {
                    "grant_type": "refresh_token",
                    "refresh_token": rt,
                    "client_id": CAPI_CLIENT_ID,
                },
                timeout=15,
            )
            self._apply_token_response(data)
            self._resolve_account_callsign_from_fleetcarrier(timeout=15)
            return True
        except Exception as e:
            print("Refresh failed:", e)
            self._clear_refresh()
            return False

    def _restore_from_refresh(self):
        rt = self._load_refresh()
        if not rt:
            return
        try:
            data = _post_json(
                "/token",
                {
                    "grant_type": "refresh_token",
                    "refresh_token": rt,
                    "client_id": CAPI_CLIENT_ID,
                },
                timeout=15,
            )
            self._apply_token_response(data)
            self._resolve_account_callsign_from_fleetcarrier(timeout=15)
        except Exception as e:
            print("Failed to restore session from refresh token:", e)

    # ---- Public helpers ----
    def is_logged_in(self) -> bool:
        if self._need_refresh():
            try:
                if not self._refresh_access():
                    return False
            except Exception:
                return False
        return self._access_jwt is not None

    def get_account_callsign(self) -> str | None:
        return self._account_callsign

    def get_session_info(self) -> dict[str, Any]:
        header = self._get_authenticated_header()
        token = header.get("Authorization", "")
        token_value = token.split(" ", 1)[1] if " " in token else ""
        token_preview = token_value
        if len(token_value) > 36:
            token_preview = f"{token_value[:18]}...{token_value[-12:]}"
        return {
            "token_type": self._token_type,
            "expires_in": max(int(self._access_exp - time.time()), 0),
            "token_preview": token_preview,
        }

    def get_capi_root_links(self, timeout: int = 20) -> dict[str, Any]:
        response = _get_capi("/", self._get_authenticated_header(), timeout=timeout)
        result: dict[str, Any] = {
            "status_code": response.status_code,
            "rels": [],
            "links": [],
            "message": None,
        }

        if not response.ok:
            result["message"] = response.text
            return result

        try:
            body = response.json()
            links = body.get("links", []) if isinstance(body, dict) else []
            dict_links = self._as_dict_list(links)
            result["links"] = dict_links
            result["rels"] = [item.get("rel") for item in dict_links if item.get("rel")]
        except Exception:
            result["message"] = "could not parse root endpoint JSON"
        return result

    @rate_limited(1, 3600)  # limit to 1 call per hour
    def get_fleetcarrier_snapshot(self, timeout: int = 20) -> dict[str, Any]:
        response = _get_capi("/fleetcarrier", self._get_authenticated_header(), timeout=timeout)
        result: dict[str, Any] = {
            "status_code": response.status_code,
            "found": False,
            "summary": {},
            "sales": [],
            "purchases": [],
            "cargo": [],
            "message": None,
        }

        if response.status_code == 200:
            payload = response.json()
            if not isinstance(payload, dict):
                result["message"] = "unexpected response format"
                return result

            name_obj = payload.get("name") if isinstance(payload, dict) else {}
            callsign = name_obj.get("callsign") if isinstance(name_obj, dict) else None
            vanity_name_hex = name_obj.get("vanityName") if isinstance(name_obj, dict) else None
            filtered_name_hex = name_obj.get("filteredVanityName") if isinstance(name_obj, dict) else None
            vanity_name = _decode_hex_text(vanity_name_hex)
            filtered_name = _decode_hex_text(filtered_name_hex)

            result["summary"] = {
                "callsign": callsign,
                "name": filtered_name or vanity_name,
                "current_system": payload.get("currentStarSystem"),
                "state": payload.get("state"),
                "balance": payload.get("balance"),
                "fuel": payload.get("fuel"),
            }

            orders = payload.get("orders") if isinstance(payload, dict) else {}
            commodities_orders = orders.get("commodities") if isinstance(orders, dict) else {}
            sales = commodities_orders.get("sales") if isinstance(commodities_orders, dict) else []
            purchases = commodities_orders.get("purchases") if isinstance(commodities_orders, dict) else []
            cargo_items = payload.get("cargo") if isinstance(payload, dict) else []

            result["sales"] = [
                {
                    "name": item.get("name"),
                    "stock": item.get("stock"),
                    "price": item.get("price"),
                    "blackmarket": item.get("blackmarket"),
                }
                for item in self._as_dict_list(sales)
            ]
            result["purchases"] = [
                {
                    "name": item.get("name"),
                    "total": item.get("total"),
                    "outstanding": item.get("outstanding"),
                    "price": item.get("price"),
                }
                for item in self._as_dict_list(purchases)
            ]
            result["cargo"] = [
                {
                    "commodity": item.get("locName") or item.get("commodity"),
                    "qty": item.get("qty"),
                    "value": item.get("value"),
                    "mission": item.get("mission"),
                    "stolen": item.get("stolen"),
                }
                for item in self._as_dict_list(cargo_items)
            ]

            result["found"] = True
            return result

        if response.status_code == 204:
            result["message"] = "no content: commander does not own a fleet carrier"
        elif response.status_code == 401:
            result["message"] = "unauthorized: access token may be invalid/expired"
            result["details"] = response.text
        elif response.status_code == 418:
            result["message"] = "service maintenance (418 teapot)"
        else:
            result["message"] = response.text

        return result

    def get_fleetcarrier_status(self, timeout: int = 20) -> dict[str, Any]:
        snapshot = self.get_fleetcarrier_snapshot(timeout=timeout)
        if not isinstance(snapshot, dict):
            return {
                "status_code": None,
                "found": False,
                "message": "no fleetcarrier snapshot available",
                "details": None,
            }
        return {
            "status_code": snapshot.get("status_code"),
            "found": bool(snapshot.get("found")),
            "message": snapshot.get("message"),
            "details": snapshot.get("details"),
        }

    def get_fleetcarrier_summary(self, timeout: int = 20) -> dict[str, Any]:
        snapshot = self.get_fleetcarrier_snapshot(timeout=timeout)
        if not isinstance(snapshot, dict):
            return {}
        summary = snapshot.get("summary")
        return summary if isinstance(summary, dict) else {}

    def get_fleetcarrier_sales(self, timeout: int = 20) -> list[dict[str, Any]]:
        snapshot = self.get_fleetcarrier_snapshot(timeout=timeout)
        if not isinstance(snapshot, dict):
            return []
        return self._as_dict_list(snapshot.get("sales"))

    def get_fleetcarrier_purchases(self, timeout: int = 20) -> list[dict[str, Any]]:
        snapshot = self.get_fleetcarrier_snapshot(timeout=timeout)
        if not isinstance(snapshot, dict):
            return []
        return self._as_dict_list(snapshot.get("purchases"))

    def get_fleetcarrier_cargo(self, timeout: int = 20) -> list[dict[str, Any]]:
        snapshot = self.get_fleetcarrier_snapshot(timeout=timeout)
        if not isinstance(snapshot, dict):
            return []
        return self._as_dict_list(snapshot.get("cargo"))

    def logout(self, forget_account: bool = False):
        self._access_jwt = None
        self._token_type = "Bearer"
        self._access_exp = 0.0
        self._claims = {}
        if forget_account:
            if self._account_callsign:
                self.remove_saved_account(self._account_callsign)
            else:
                self._clear_refresh()
        print("Logged out.")
        self._emit("SIGNED_OUT")


class CapiAccountManager:
    def __init__(self):
        self._handlers: dict[str, AuthHandler] = {}

    def list_accounts(self) -> list[str]:
        return AuthHandler.list_saved_callsigns()

    def add_account_via_login(self) -> str:
        handler = AuthHandler(auto_restore=False)
        if not handler.login():
            raise RuntimeError("Login failed")

        callsign = handler.get_account_callsign()
        if not callsign:
            raise RuntimeError("Could not resolve carrier callsign for this account")

        self._handlers[callsign] = handler
        return callsign

    def get_handler(self, callsign: str, require_logged_in: bool = True) -> AuthHandler:
        normalized = _normalize_callsign(callsign)
        if not normalized:
            raise ValueError("A valid carrier callsign is required")

        existing = self._handlers.get(normalized)
        if existing is not None:
            if not require_logged_in or existing.is_logged_in():
                return existing

        handler = AuthHandler(callsign=normalized, auto_restore=True)
        if require_logged_in and not handler.is_logged_in():
            raise RuntimeError(f"No active session for account {normalized}")

        self._handlers[normalized] = handler
        return handler

    def remove_account(self, callsign: str) -> None:
        normalized = _normalize_callsign(callsign)
        if not normalized:
            return
        self._handlers.pop(normalized, None)
        AuthHandler.remove_saved_account(normalized)

if __name__ == "__main__":
    manager = CapiAccountManager()
    account_callsigns = manager.list_accounts()

    if not account_callsigns:
        print("No saved Frontier CAPI accounts found. Starting login flow...")
        first_callsign = manager.add_account_via_login()
        account_callsigns = [first_callsign]

    print(f"saved_accounts={', '.join(account_callsigns)}")

    for account_callsign in account_callsigns:
        print("\n" + "=" * 72)
        print(f"CAPI account: {account_callsign}")
        print("=" * 72)

        try:
            auth = manager.get_handler(account_callsign, require_logged_in=True)
        except Exception as e:
            print(f"Could not activate account {account_callsign}: {e}")
            continue

        session_info = auth.get_session_info()
        print("CAPI session ready")
        print(f"token_type={session_info['token_type']}  expires_in={session_info['expires_in']}s")
        print(f"token_preview={session_info['token_preview']}")
        print(f"account_callsign={auth.get_account_callsign()}")

        print("[CAPI] GET /")
        root_info = auth.get_capi_root_links()
        print("status:", root_info.get("status_code"))
        if root_info.get("status_code") == 200:
            rels = root_info.get("rels", [])
            print("available rels:", ", ".join(rels) if rels else "(none)")
        else:
            print(root_info.get("message"))

        print("\n[CAPI] GET /fleetcarrier")
        fc_status = auth.get_fleetcarrier_status()
        print("status:", fc_status.get("status_code"))

        if fc_status.get("status_code") == 200 and fc_status.get("found"):
            summary = auth.get_fleetcarrier_summary()
            print("fleet carrier found")
            print(f"callsign={summary.get('callsign')}  name={summary.get('name')}")
            print(f"system={summary.get('current_system')}  state={summary.get('state')}")
            print(f"balance={summary.get('balance')}  fuel={summary.get('fuel')}")

            if summary.get("callsign") and summary.get("callsign") != account_callsign:
                print(
                    f"warning: keyed callsign {account_callsign} differs from "
                    f"CAPI summary callsign {summary.get('callsign')}"
                )

            print("\norders.commodities.sales:")
            sales = auth.get_fleetcarrier_sales()
            if sales:
                for item in sales:
                    print(
                        f"  - name={item.get('name')} stock={item.get('stock')} "
                        f"price={item.get('price')} blackmarket={item.get('blackmarket')}"
                    )
            else:
                print("  (none)")

            print("\norders.commodities.purchases:")
            purchases = auth.get_fleetcarrier_purchases()
            if purchases:
                for item in purchases:
                    print(
                        f"  - name={item.get('name')} total={item.get('total')} "
                        f"outstanding={item.get('outstanding')} price={item.get('price')}"
                    )
            else:
                print("  (none)")

            print("\ncargo:")
            cargo = auth.get_fleetcarrier_cargo()
            if cargo:
                for item in cargo:
                    print(
                        f"  - commodity={item.get('commodity')} "
                        f"qty={item.get('qty')} value={item.get('value')} "
                        f"mission={item.get('mission')} stolen={item.get('stolen')}"
                    )
            else:
                print("  (none)")
        else:
            print(fc_status.get("message"))
            if fc_status.get("details"):
                print(fc_status.get("details"))
