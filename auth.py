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
from postgrest import APIResponse
from supabase import create_client, Client, FunctionsHttpError

from config import SUPABASE_URL, SUPABASE_KEY, LOCAL_PORT, REDIRECT_URL
from decos import rate_limited

# =========
# Constants
# =========

load_dotenv()  # load .env file if present
# Your Next.js dashboard domain hosting /api/auth/exchange and /api/auth/refresh
AUTH_SERVER = os.getenv(
    "AUTH_SERVER",
    "https://edcm.app",
)

# Discord application (reads from env, falls back to your current ID)
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "1419228023118364703")

# Scopes: external login only asks for `identify` (no email); PTN flow can add `guilds.members.read`.
BASE_SCOPES = "identify"

# Vercel protection-bypass (optional, for preview deployments)
VERCEL_BYPASS = os.getenv("VERCEL_BYPASS_TOKEN")

KEYRING_SERVICE = "edcm"
KEYRING_ACCOUNT = "refresh_token"

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
    headers = {}
    if VERCEL_BYPASS:
        headers["x-vercel-protection-bypass"] = VERCEL_BYPASS
    r = requests.post(url, json=payload, headers=headers, timeout=timeout)
    if r.status_code >= 400:
        print("POST", url, "->", r.status_code, r.text)
        r.raise_for_status()
    return r.json()

def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    return verifier, challenge

def _discord_auth_url(scopes: str, code_challenge: str, state: str) -> str:
    params = {
        "client_id": DISCORD_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URL, 
        "scope": scopes,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
        "prompt": "none",
    }
    return requests.Request("GET", "https://discord.com/api/oauth2/authorize", params=params).prepare().url

def _b64pad(s: str) -> str:
    return s + "=" * (-len(s) % 4)

def _is_uuid(s: str | None) -> bool:
    return bool(s and UUID_RE.match(s))

def _is_snowflake(s: str | None) -> bool:
    return bool(s and SNOWFLAKE_RE.match(s))

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

    def __init__(self):
        self.client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        self._access_jwt: Optional[str] = None
        self._access_exp: float = 0.0
        self._jwt_verifier = JwtVerifier(SUPABASE_URL)
        self._claims: Dict[str, Any] = {}

        # Simple event bus
        self._auth_event_callbacks: dict[str, list[Callable[[], None]]] = {
            "SIGNED_IN": [], "SIGNED_OUT": []
        }

        # Try to restore session (silent)
        self._restore_from_refresh()

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

    # ---- Token cache / client wiring ----
    def _apply_client_auth(self):
        if self._access_jwt:
            try:
                self.client.postgrest.auth(self._access_jwt)  # type: ignore[attr-defined]
            except Exception:
                pass

    def _store_refresh(self, token: str):
        keyring.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, token)

    def _load_refresh(self) -> Optional[str]:
        try:
            return keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
        except Exception:
            return None

    def _clear_refresh(self):
        try:
            keyring.delete_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
        except Exception:
            pass

    def _set_access(self, access_jwt: str, refresh_token: Optional[str] = None):
        self._claims = self._jwt_verifier.decode_verify(access_jwt)
        self._access_jwt = access_jwt
        self._access_exp = float(self._claims.get("exp", 0))
        if refresh_token:
            self._store_refresh(refresh_token)
        self._apply_client_auth()

    def _need_refresh(self) -> bool:
        return (self._access_jwt is None) or (time.time() >= self._access_exp - 30)
    
    def _auth_header(self) -> dict:
        return {"Authorization": f"Bearer {self._access_jwt}"} if self._access_jwt else {}

    # ---- External login (identify only) ----
    def login(self) -> bool:
        verifier, challenge = _pkce_pair()
        state = secrets.token_urlsafe(24)

        # Start local callback server loop
        t = threading.Thread(target=_run_callback_server, args=(self._render_page,), daemon=True)
        t.start()

        # Authorize in browser
        url = _discord_auth_url(BASE_SCOPES, challenge, state)
        print("Your browser has been opened to sign in with Discord.")
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

        # Exchange on dashboard: returns { access_jwt, refresh_token }
        data = _post_json(
            "/api/auth/exchange",
            {
                "code": result["code"],
                "code_verifier": verifier,
                "redirect_uri": REDIRECT_URL,
                "user_agent": "EDCM Desktop",
            },
            timeout=20,
        )
        self._set_access(data["access_jwt"], data.get("refresh_token"))
        self._emit("SIGNED_IN")
        return True

    def _refresh_access(self) -> bool:
        rt = self._load_refresh()
        if not rt:
            return False
        try:
            data = _post_json(
                "/api/auth/refresh",
                {"refresh_token": rt, "user_agent": "EDCM Desktop"},
                timeout=15,
            )
            self._set_access(data["access_jwt"], data.get("refresh_token"))
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
                "/api/auth/refresh",
                {"refresh_token": rt, "user_agent": "EDCM Desktop"},
                timeout=15,
            )
            self._set_access(data["access_jwt"], data.get("refresh_token"))
        except Exception as e:
            print("Failed to restore session from refresh token:", e)

    # ---- Public helpers ----
    def is_logged_in(self) -> bool:
        if self._need_refresh():
            try:
                self._refresh_access()
            except Exception:
                return False
        return self._access_jwt is not None

    def get_client(self) -> Client:
        if self._need_refresh():
            self._refresh_access()
        return self.client

    def logout(self):
        self._access_jwt = None
        self._access_exp = 0.0
        self._clear_refresh()
        print("Logged out.")
        self._emit("SIGNED_OUT")

    def get_user(self) -> Optional[dict]:
        if not self.is_logged_in():
            return None
        try:
            if not self._claims:
                return None
            # For custom JWT, sub is Discord snowflake; for any legacy token, it could be UUID.
            return {
                "id": self._claims.get("sub"),
                "discord_id": self._claims.get("sub") if _is_snowflake(self._claims.get("sub")) else None,
                "username": self._claims.get("username") or self._claims.get("discord_username"),
                "claims": self._claims,
            }
        except Exception:
            return None

    def get_username(self) -> Optional[str]:
        u = self.get_user()
        return u.get("username") if u else None

    # ---- Just-in-time user OAuth for PTN (identify + guilds.members.read) ----
    def _discord_user_token(self, scopes: str = "identify guilds.members.read") -> str:
        verifier, challenge = _pkce_pair()
        state = secrets.token_urlsafe(24)

        t = threading.Thread(target=_run_callback_server, args=(self._render_page,), daemon=True)
        t.start()

        url = _discord_auth_url(scopes, challenge, state)
        print("Your browser has been opened to verify PTN membership.")
        webbrowser.open(url)

        t.join()
        result = _CallbackHandler.result
        if result.get("error"):
            raise RuntimeError(f"OAuth error: {result['error']}")
        if not result.get("code"):
            raise RuntimeError("Timeout waiting for OAuth callback")
        if result.get("state") != state:
            raise RuntimeError("State mismatch during OAuth")

        data = _post_json(
            "/api/auth/discord-token",
            {
                "code": result["code"],
                "code_verifier": verifier,
                "redirect_uri": REDIRECT_URL,
                "user_agent": "EDCM Desktop",
            },
            timeout=20,
        )
        token = data.get("discord_access_token")
        if not token:
            raise RuntimeError("No discord_access_token returned by /api/auth/discord-token")
        return token  # short-lived; we do NOT store this

    def invoke_edge(self, name: str, body: Any | None = None, *, method: str = "POST", expect_json: bool = True) -> dict | str | APIResponse:
        """
        Call a Supabase Edge Function with the current access token.
        If we get 401/403, try exactly one refresh and retry.
        Raises FunctionsHttpError (e.g., 429) or RuntimeError on unexpected conditions.
        """
        if not self.is_logged_in():
            raise FunctionsHttpError("Unauthorized", 401, "No access token")

        def _call():
            return self.client.functions.invoke(
                name,
                invoke_options={
                    "method": method,
                    "headers": self._auth_header(),
                    "body": body,
                },
            )

        try:
            res = _call()
        except FunctionsHttpError as e:
            if e.status in (401, 403):
                # one refresh attempt
                if self._refresh_access():
                    res = _call()
                else:
                    print("Failed to refresh access token after 401/403")
                    self.logout()
                    raise
            else:
                raise

        # supabase-py returns bytes for body; normalize
        if isinstance(res, bytes):
            txt = res.decode("utf-8", errors="replace")
            if expect_json:
                try:
                    return json.loads(txt)
                except Exception:
                    return {"raw": txt}
            return txt

        return res


    # -------------------------
    # PTN role-related methods
    # -------------------------

    def auth_PTN_roles(self) -> tuple[bool | None, list[str]]:
        """
        Verify PTN roles without Supabase Auth:
        - Uses our app access JWT for Authorization to edge function
        - Gets a short-lived Discord user token with guilds.members.read
        - Calls 'check-ptn-roles' and discards the user token
        """
        if not self.is_logged_in():
            print("User is not logged in.")
            return None, []

        discord_access_token = self._discord_user_token("identify guilds.members.read")
        try:
            result = self.client.functions.invoke(
                "check-ptn-roles",
                invoke_options={
                    "headers": {"Authorization": f"Bearer {self._access_jwt}"},
                    "body": {"discord_access_token": discord_access_token},
                },
            )
            if type(result) is not bytes:
                print(f"Unexpected response type from check-ptn-roles: {result}")
                return None, []
            data: dict = json.loads(result)
            return data.get("inPTN", False), data.get("roleKeys", [])
        except Exception as e:
            print(f"Error while checking PTN roles: {e}")
            return None, []

    def can_bulk_report(self) -> bool:
        """Use edge function; server should derive identity from Authorization JWT."""
        if not self.is_logged_in():
            return False
        try:
            result = self.client.functions.invoke(
                "can-bulk-report",
                invoke_options={
                    "headers": {"Authorization": f"Bearer {self._access_jwt}"},
                    "body": {}, 
                },
            )
            if type(result) is not bytes:
                print(f"Unexpected response type from can-bulk-report: {result}")
                return False
            data: dict = json.loads(result)
            return data.get("authorized", False)
        except Exception as e:
            print(f"Error while checking bulk report permission: {e}")
            return False

if __name__ == "__main__":
    auth = AuthHandler()
    if not auth.is_logged_in():
        auth.login()
    print("Username:", auth.get_username())
    print("Can bulk report:", auth.can_bulk_report())
