from functools import partial
import json
import webbrowser
import threading
import keyring
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from postgrest import APIResponse
from typing import Literal, Callable
from supabase import create_client, Client
from supabase_auth import UserResponse
from config import SUPABASE_URL, SUPABASE_KEY, LOCAL_PORT, REDIRECT_URL
from decos import rate_limited

# An event to signal when the authentication is complete
auth_complete = threading.Event()

class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """A server to handle the OAuth redirect and exchange the code for a session."""
    def __init__(self, supabase_client: Client, *args, **kwargs):
        self.supabase_client = supabase_client
        super().__init__(*args, **kwargs)

    def _render_page(self,
                     title: str,
                     heading: str,
                     messages: list[str],
                     ) -> bytes:
        """Return a reusable dark-themed HTML page."""
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
        </html>
        """
        return html.encode('utf-8')

    def do_GET(self):
        # Parse the URL and extract the authorization code
        parsed_path = urlparse(self.path)
        query_params = parse_qs(parsed_path.query)
        code = query_params.get("code", [None])[0]

        if code:
            try:
                # Exchange the code for a valid session
                # This function also automatically sets the session in the client
                self.supabase_client.auth.exchange_code_for_session({'auth_code': code})

                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()

                self.wfile.write(self._render_page(
                    title="Authentication Successful",
                    heading="Authentication successful!",
                    messages=["You can close this window and return to the EDCM."]
                ))

            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(self._render_page(
                    title="Authentication Failed",
                    heading="Authentication failed!",
                    messages=[f"EDCM was unable to complete your sign-in.", f"<em>Error details:</em> {e}", "Please close this window and try again."]
                ))
            finally:
                # Signal the main thread to continue, regardless of success or failure
                auth_complete.set()
        else:
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(self._render_page(
                title="Authentication Failed",
                heading="Authentication failed!",
                messages=["No authorization code was received.", "Please close this window and try again."]
            ))
            auth_complete.set()

    def log_message(self, format, *args):
        # Silences the default server logging
        return

class AuthHandler:
    """Handles the authentication flow with Supabase and Discord."""
    def __init__(self):
        self.client = create_client(SUPABASE_URL, SUPABASE_KEY)
        self._auth_event_callbacks: dict[Literal['SIGNED_IN', 'SIGNED_OUT', 'TOKEN_REFRESHED', 'USER_UPDATED', 'USER_DELETED', 'PASSWORD_RECOVERY', 'MFA_CHALLENGE_VERIFIED'], Callable[[], None]] = {
            'SIGNED_IN': lambda: None,
            'SIGNED_OUT': lambda: None,
            'TOKEN_REFRESHED': lambda: None,
            'USER_UPDATED': lambda: None,
            'USER_DELETED': lambda: None,
            'PASSWORD_RECOVERY': lambda: None,
            'MFA_CHALLENGE_VERIFIED': lambda: None,
        }
        self.client.auth.on_auth_state_change(self._auth_state_changed)
        self._load_cached_session()

    def _start_auth_flow(self, request_guilds: bool = False, client: Client | None = None):
        """Initializes the full authentication flow."""
        # make sure previous runs don't leave the event set
        auth_complete.clear()

        server_address = ('localhost', LOCAL_PORT)
        handler = partial(OAuthCallbackHandler, client if client else self.client)
        httpd = HTTPServer(server_address, handler)

        server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        server_thread.start()

        scope = "identify"
        if request_guilds:
            scope += " guilds.members.read"
        data = client.auth.sign_in_with_oauth({
            "provider": "discord",
            "options": {"redirect_to": REDIRECT_URL, "scopes": scope}
        })

        print("Your browser has been opened to sign in with Discord...")
        webbrowser.open(data.url)

        # wait for the callback to set the event
        auth_complete.wait()

        # cleanly tear down the server
        httpd.shutdown()
        httpd.server_close()
        server_thread.join()

    def login(self, request_guilds: bool = False, client: Client = None) -> UserResponse | None:
        """Starts the login process."""
        self._start_auth_flow(request_guilds=request_guilds, client=client if client else self.client)
        # Now, the client should have the session. Let's verify.
        try:
            user = self.client.auth.get_user()
            if user:
                print("✅ Sign-in successful!")
                print(f"User ID: {user.user.id}")
                print(f"Discord Username: {user.user.user_metadata['full_name']}")
                print(f'user.user.user_metadata: {user.user.user_metadata}')
                self._cache_session()
                return user
            else:
                print("❌ Authentication failed. Could not retrieve user.")
                return None
        except Exception as e:
            print(f"❌ An error occurred while fetching the user: {e}")
            return None

    def _refresh_session(self):
        """Refreshes the user's session."""
        try:
            self.client.auth.refresh_session()
            print("Session refreshed.")
            self._cache_session()
        except Exception as e:
            print(f"Error refreshing session: {e}")

    def _auth_state_changed(self, event: Literal['SIGNED_IN', 'SIGNED_OUT', 'TOKEN_REFRESHED', 'USER_UPDATED', 'USER_DELETED', 'PASSWORD_RECOVERY', 'MFA_CHALLENGE_VERIFIED'], session):
        """Callback for authentication state changes."""
        print(f"Auth event: {event}")
        if event == "SIGNED_IN":
            print("User signed in.")
        elif event == "SIGNED_OUT":
            print("User signed out.")
        elif event == "TOKEN_REFRESHED":
            print("Session token refreshed.")
            self._cache_session()
        elif event == "USER_UPDATED":
            print("User information updated.")
        elif event == "USER_DELETED":
            print("User account deleted.")
        elif event == "PASSWORD_RECOVERY":
            print("Password recovery initiated.")
        elif event == "MFA_CHALLENGE_VERIFIED":
            print("MFA challenge verified.")
        else:
            print(f"Unhandled auth event: {event}")
        threading.Thread(target=self._auth_event_callbacks.get(event, lambda: None)).start()

    def _cache_session(self):
        """Cache only the refresh token (to stay under credential‐store size limits)."""
        session = self.client.auth.get_session()
        if session and session.refresh_token:
            keyring.set_password("edcm", "refresh_token", session.refresh_token)
            print("Refresh token cached securely via keyring.")
        else:
            print("No refresh token to cache.")

    def _load_cached_session(self):
        """Load the refresh token from the vault, then refresh to get a new access token."""
        rt = keyring.get_password("edcm", "refresh_token")
        if rt:
            try:
                self.client.auth.set_session(None, rt)
            except Exception as e:
                print(f"Failed to set session from refresh token: {e}")
        else:
            print("No refresh token found in keyring.")

    def _clear_cached_session(self):
        """Clears the cached session file."""
        try:
            keyring.delete_password("edcm", "refresh_token")
            print("Cached session cleared.")
        except Exception as e:
            print(f"Error clearing cached session: {e}")

    def register_auth_event_callback(self, event: Literal['SIGNED_IN', 'SIGNED_OUT', 'TOKEN_REFRESHED', 'USER_UPDATED', 'USER_DELETED', 'PASSWORD_RECOVERY', 'MFA_CHALLENGE_VERIFIED'], callback: Callable[[], None]):
        """Registers a callback for a specific authentication event."""
        if event not in self._auth_event_callbacks:
            raise ValueError(f"Unsupported event type: {event}")
        self._auth_event_callbacks[event] = callback

    def logout(self):
        """Logs out the current user."""
        self.client.auth.sign_out()
        print("Logged out.")
        self._clear_cached_session()

    def delete_account(self) -> bool:
        """Deletes the current user's account."""
        user = self.get_user()
        if not user:
            print("No authenticated user to delete.")
            return False
        try:
            response: dict|bytes = self.client.functions.invoke(
                "delete-user",
                invoke_options={
                    "headers": {"Authorization": f"Bearer {self.client.auth.get_session().access_token}"},
                },
            )
            response: dict = response if isinstance(response, dict) else json.loads(response)
            if response.get("status") == 200:
                print("Account deleted successfully.")
                self.logout()
                return True
            else:
                print(f"Failed to delete account: {response.get('status')} - {response}")
                return False
        except Exception as e:
            print(f"Error deleting account: {e}")
            return False

    def is_logged_in(self) -> bool:
        """Returns whether a user is currently logged in."""
        return self.get_user() is not None
    
    def get_client(self) -> Client:
        """Returns the Supabase client with the current session."""
        return self.client
    
    def get_user(self) -> UserResponse | None:
        """Returns the current authenticated user, or None if not signed in."""
        try:
            user = self.client.auth.get_user()
            return user if user else None
        except Exception as e:
            print(f"Error fetching user: {e}")
            return None
        
    def get_username(self) -> str | None:
        """Returns the Discord username of the current user, or None if not signed in."""
        user = self.get_user()
        if user:
            return user.user.user_metadata.get('full_name', None)
        return None

    def auth_PTN_roles(self) -> tuple[bool|None, list[str]]:
        """Updates the user's PTN roles with the Supabase function."""
        client = create_client(SUPABASE_URL, SUPABASE_KEY)
        self._start_auth_flow(request_guilds=True, client=client)
        if not client.auth.get_user():
            print("Login failed.")
            return None, []
        session = client.auth.get_session()
        if not session:
            print("No active session.")
            return None, []
        jwt = session.access_token
        discord_access_token = session.provider_token
        result = client.functions.invoke(
            "check-ptn-roles",
            invoke_options={
                "headers": {"Authorization": f"Bearer {jwt}"},
                "body": {"discord_access_token": discord_access_token},
            },
        )
        print(result)
        if type(result) is not bytes:
            print(f"Unexpected response type from check-ptn-roles: {result}")
            return None
        data: dict = json.loads(result)
        return data.get('inPTN', False), data.get('roleKeys', [])

    @rate_limited(max_calls=5, period=60)
    def get_PTN_roles(self) -> list[str] | None:
        """Fetches the user's PTN roles from the Supabase table."""
        if not self.is_logged_in():
            print("User is not logged in.")
            return None
        try:
            user = self.client.auth.get_user()
            if not user:
                print("No authenticated user found.")
                return None
            user_id = user.user.id
            response: APIResponse = self.client.from_("ptn_member_roles").select("role_names").eq("user_id", user_id).execute()
            if response.data:
                print(f"Fetched PTN roles: {response.data[0].get('role_names', None)}")
                return response.data[0].get('role_names', None)
            else:
                print("No PTN roles found for the user.")
                return None
        except Exception as e:
            print(f"Error while fetching PTN roles: {e}")
            return None

    @rate_limited(max_calls=5, period=60)
    def get_highest_PTN_role_level(self) -> Literal["Elevated", "CCO", "Senior", "Moderator", "Council"] | None:
        """Fetches the user's highest role level in PTN from the Supabase table."""
        if not self.is_logged_in():
            print("User is not logged in.")
            return None
        try:
            user = self.client.auth.get_user()
            if not user:
                print("No authenticated user found.")
                return None
            user_id = user.user.id
            response: APIResponse = self.client.from_("ptn_member_roles").select("highest_level, updated_at").eq("user_id", user_id).execute()
            if response.data:
                print(f"Fetched highest-level info: {response.data[0].get('highest_level', None)}")
                return response.data[0].get('highest_level', None)
            else:
                print("No highest-level info found for the user.")
                return None
        except Exception as e:
            print(f"Error while fetching highest-level info: {e}")
            return None
        
    def can_bulk_report(self) -> bool:
        """Returns whether the user has permission to use bulk report features."""
        if not self.is_logged_in():
            return False
        try:
            user = self.client.auth.get_user()
            if not user:
                print("No authenticated user found.")
                return False
            user_id = user.user.id
            result = self.client.functions.invoke(
                "can-bulk-report",
                invoke_options={
                    "headers": {"Authorization": f"Bearer {self.client.auth.get_session().access_token}"},
                    "body": {"user_id": user_id},
                },
            )
            if type(result) is not bytes:
                print(f"Unexpected response type from can-bulk-report: {result}")
                return False
            result: dict = json.loads(result)
            return result.get("authorized", False)
        except Exception as e:
            print(f"Error while checking bulk report permission: {e}")
            return False
    
    def is_PTN_elevated(self) -> bool:
        """Returns whether the user has at least the 'Elevated' role level in PTN."""
        level = self.get_highest_PTN_role_level()
        if level is None:
            return False
        return level in ["Elevated", "CCO", "Senior", "Moderator", "Council"]

    def is_PTN_senior(self) -> bool:
        """Returns whether the user has at least the 'Senior' role level in PTN."""
        level = self.get_highest_PTN_role_level()
        if level is None:
            return False
        return level in ["Senior", "Moderator", "Council"]

if __name__ == "__main__":
    auth_handler = AuthHandler()
    print(auth_handler.can_bulk_report())