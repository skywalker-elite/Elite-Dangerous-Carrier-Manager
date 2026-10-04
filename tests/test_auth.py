"""Authentication with fake keyring, token verifier, HTTP, browser, and callback server."""
import base64
import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from unittest.mock import Mock

import pytest
import requests

import auth


@pytest.fixture
def auth_environment(monkeypatch):
    tokens = {}
    client = SimpleNamespace(postgrest=SimpleNamespace(auth=Mock()), functions=SimpleNamespace(invoke=Mock()))
    clock = [1000.0]
    claims = {"sub": "123456789012345678", "username": "Synthetic Commander", "exp": 2000}
    verifier = SimpleNamespace(decode_verify=Mock(side_effect=lambda token: dict(claims)))
    post = Mock(return_value={"access_jwt": "fresh-access", "refresh_token": "rotated-refresh"})
    browser = Mock(return_value=True)
    monkeypatch.setattr(auth, "create_client", Mock(return_value=client))
    monkeypatch.setattr(auth, "JwtVerifier", Mock(return_value=verifier))
    monkeypatch.setattr(auth, "time", SimpleNamespace(time=lambda: clock[0]))
    monkeypatch.setattr(auth, "_post_json", post)
    monkeypatch.setattr(auth.webbrowser, "open", browser)
    monkeypatch.setattr(auth.keyring, "get_password", lambda service, key: tokens.get((service, key)))
    monkeypatch.setattr(auth.keyring, "set_password", lambda service, key, token: tokens.__setitem__((service, key), token))
    monkeypatch.setattr(auth.keyring, "delete_password", lambda service, key: tokens.pop((service, key), None))
    monkeypatch.setattr(auth._CallbackHandler, "result", {"code": None, "state": None, "error": None})
    return SimpleNamespace(tokens=tokens, client=client, clock=clock, claims=claims, verifier=verifier, post=post, browser=browser)


def test_no_stored_refresh_starts_logged_out(auth_environment):
    handler = auth.AuthHandler()
    assert handler.is_logged_in() is False
    assert handler.get_user() is None
    assert handler.get_username() is None
    auth_environment.post.assert_not_called()


def test_restores_session_and_rotates_refresh_token(auth_environment):
    env = auth_environment
    env.tokens[(auth.KEYRING_SERVICE, auth.KEYRING_ACCOUNT)] = "stored-refresh"
    handler = auth.AuthHandler()
    assert handler.is_logged_in() is True
    assert handler.get_user()["discord_id"] == env.claims["sub"]
    assert handler.get_username() == "Synthetic Commander"
    assert env.post.call_args.args[0] == "/api/auth/refresh"
    assert env.post.call_args.args[1]["refresh_token"] == "stored-refresh"
    assert env.tokens[(auth.KEYRING_SERVICE, auth.KEYRING_ACCOUNT)] == "rotated-refresh"
    env.client.postgrest.auth.assert_called_once_with("fresh-access")


@pytest.mark.parametrize("failure", [requests.Timeout("offline"), ValueError("malformed response")])
def test_restore_failure_leaves_session_logged_out(auth_environment, failure):
    env = auth_environment
    env.tokens[(auth.KEYRING_SERVICE, auth.KEYRING_ACCOUNT)] = "stored-refresh"
    env.post.side_effect = failure
    handler = auth.AuthHandler()
    assert handler.is_logged_in() is False
    assert handler.get_user() is None


def test_refresh_at_expiry_boundary_and_logout_event(auth_environment):
    env = auth_environment
    handler = auth.AuthHandler()
    handler._set_access("original", "refresh")
    env.clock[0] = 1969.999
    assert handler.is_logged_in()
    env.post.assert_not_called()
    env.clock[0] = 1970
    assert handler.is_logged_in()
    env.post.assert_called_once()
    signed_out = Mock()
    handler.register_auth_event_callback("SIGNED_OUT", signed_out)
    handler.logout()
    assert not handler.is_logged_in()
    assert handler.get_user() is None
    assert not env.tokens
    signed_out.assert_called_once_with()


@pytest.mark.parametrize("stored_refresh", [True, False])
def test_failed_refresh_cannot_keep_expired_session_logged_in(auth_environment, stored_refresh):
    env = auth_environment
    handler = auth.AuthHandler()
    handler._set_access("expired-access", "refresh" if stored_refresh else None)
    env.clock[0] = 2001
    env.post.side_effect = requests.HTTPError("refresh rejected")
    assert handler.is_logged_in() is False
    assert handler.get_user() is None


def test_rejected_access_token_does_not_establish_session(auth_environment):
    env = auth_environment
    handler = auth.AuthHandler()
    env.verifier.decode_verify.side_effect = auth.InvalidTokenError("invalid signature")
    with pytest.raises(auth.InvalidTokenError):
        handler._set_access("invalid", "do-not-store")
    assert handler.is_logged_in() is False
    assert not env.tokens
    env.client.postgrest.auth.assert_not_called()


def test_event_callbacks_are_isolated_and_can_unregister(auth_environment):
    handler = auth.AuthHandler()
    failing = Mock(side_effect=RuntimeError("broken subscriber"))
    healthy = Mock()
    handler.register_auth_event_callback("SIGNED_OUT", failing)
    handler.register_auth_event_callback("SIGNED_OUT", healthy)
    handler.logout()
    healthy.assert_called_once_with()
    handler.unregister_auth_event_callback("SIGNED_OUT", healthy)
    handler.logout()
    assert healthy.call_count == 1
    with pytest.raises(ValueError):
        handler.register_auth_event_callback("NOT_AN_EVENT", healthy)


@pytest.fixture
def oauth_callback(monkeypatch):
    result = {"code": "authorization-code", "state": "expected-state"}

    class ImmediateThread:
        def __init__(self, target, args, daemon):
            self.target, self.args = target, args
            assert daemon

        def start(self):
            self.target(*self.args)

        def join(self):
            pass

    def callback(render):
        auth._CallbackHandler.result = dict(result)

    monkeypatch.setattr(auth, "threading", SimpleNamespace(Thread=ImmediateThread))
    monkeypatch.setattr(auth, "_run_callback_server", callback)
    monkeypatch.setattr(auth.secrets, "token_urlsafe", lambda length: "expected-state")
    monkeypatch.setattr(auth, "_pkce_pair", lambda: ("verifier", "challenge"))
    return result


def test_oauth_success_exchanges_code_and_emits_signed_in(auth_environment, oauth_callback):
    env = auth_environment
    handler = auth.AuthHandler()
    callback = Mock()
    handler.register_auth_event_callback("SIGNED_IN", callback)
    assert handler.login() is True
    callback.assert_called_once_with()
    assert handler.is_logged_in()
    payload = env.post.call_args.args[1]
    assert payload["code"] == "authorization-code"
    assert payload["code_verifier"] == "verifier"
    assert payload["redirect_uri"] == auth.REDIRECT_URL
    query = parse_qs(urlparse(env.browser.call_args.args[0]).query)
    assert query["state"] == ["expected-state"]
    assert query["code_challenge_method"] == ["S256"]


@pytest.mark.parametrize("result", [
    {"error": "access_denied"}, {"code": None, "state": None},
    {"code": "authorization-code", "state": "wrong-state"},
])
def test_oauth_errors_and_state_mismatch_never_exchange_tokens(auth_environment, oauth_callback, result):
    oauth_callback.clear()
    oauth_callback.update(result)
    handler = auth.AuthHandler()
    with pytest.raises(RuntimeError):
        handler.login()
    auth_environment.post.assert_not_called()
    assert not handler.is_logged_in()


def test_discord_role_token_is_transient(auth_environment, oauth_callback):
    env = auth_environment
    handler = auth.AuthHandler()
    env.post.return_value = {"discord_access_token": "transient-token"}
    assert handler._discord_user_token() == "transient-token"
    assert not env.tokens
    assert not handler.is_logged_in()
    assert env.post.call_args.args[0] == "/api/auth/discord-token"


def test_callback_server_handles_success_and_closes(monkeypatch):
    server = Mock()
    server.handle_request.side_effect = lambda: setattr(auth._CallbackHandler, "result", {"code": "ok", "state": "state"})
    monkeypatch.setattr(auth, "HTTPServer", Mock(return_value=server))
    monkeypatch.setattr(auth._CallbackHandler, "result", {})
    monkeypatch.setattr(auth._CallbackHandler, "render_html", lambda *args: b"page")
    auth._run_callback_server(lambda *args: b"page", timeout_sec=1)
    server.handle_request.assert_called_once_with()
    server.server_close.assert_called_once_with()


def test_oauth_error_callback_closes_server_without_worker_exception(monkeypatch):
    server = Mock()
    handler = object.__new__(auth._CallbackHandler)
    handler.path = "/callback?error=access_denied"
    handler._send = Mock()
    server.handle_request.side_effect = handler.do_GET
    monkeypatch.setattr(auth, "HTTPServer", Mock(return_value=server))
    monkeypatch.setattr(auth._CallbackHandler, "result", {})
    monkeypatch.setattr(auth._CallbackHandler, "render_html", lambda *args: b"page")
    try:
        auth._run_callback_server(lambda *args: b"page", timeout_sec=1)
    finally:
        assert server.server_close.call_count == 1, "OAuth callback server was not closed"
    assert auth._CallbackHandler.result.get("error") == "access_denied"
    assert handler._send.call_args.args[0] == 400


def test_callback_timeout_closes_server(monkeypatch):
    clock = iter([100, 101])
    server = Mock()
    monkeypatch.setattr(auth, "HTTPServer", Mock(return_value=server))
    monkeypatch.setattr(auth, "time", SimpleNamespace(time=lambda: next(clock)))
    monkeypatch.setattr(auth._CallbackHandler, "result", {})
    monkeypatch.setattr(auth._CallbackHandler, "render_html", lambda *args: b"page")
    auth._run_callback_server(lambda *args: b"page", timeout_sec=1)
    server.handle_request.assert_not_called()
    server.server_close.assert_called_once_with()


@pytest.mark.parametrize("payload,expect_json,expected", [
    (b'{"count": 3}', True, {"count": 3}),
    (b"not json", True, {"raw": "not json"}),
    (b"plain text", False, "plain text"),
])
def test_edge_response_normalization(auth_environment, payload, expect_json, expected):
    env = auth_environment
    handler = auth.AuthHandler()
    handler._set_access("access")
    env.client.functions.invoke.return_value = payload
    assert handler.invoke_edge("synthetic", {"value": 2}, expect_json=expect_json) == expected
    options = env.client.functions.invoke.call_args.kwargs["invoke_options"]
    assert options["headers"]["Authorization"] == "Bearer access"
    assert options["body"] == {"value": 2}


@pytest.mark.parametrize("status", [401, 403])
def test_edge_auth_failure_refreshes_once_and_retries(auth_environment, status):
    env = auth_environment
    handler = auth.AuthHandler()
    handler._set_access("access", "refresh")
    env.client.functions.invoke.side_effect = [auth.FunctionsHttpError("rejected", status), b'{"count": 4}']
    assert handler.invoke_edge("synthetic") == {"count": 4}
    assert env.client.functions.invoke.call_count == 2
    env.post.assert_called_once()


def test_edge_repeated_auth_failure_stops_after_one_retry(auth_environment):
    env = auth_environment
    handler = auth.AuthHandler()
    handler._set_access("access", "refresh")
    env.client.functions.invoke.side_effect = auth.FunctionsHttpError("rejected", 401)
    with pytest.raises(auth.FunctionsHttpError):
        handler.invoke_edge("synthetic")
    assert env.client.functions.invoke.call_count == 2
    env.post.assert_called_once()


def test_edge_non_auth_failure_does_not_refresh(auth_environment):
    env = auth_environment
    handler = auth.AuthHandler()
    handler._set_access("access", "refresh")
    env.client.functions.invoke.side_effect = auth.FunctionsHttpError("limited", 429)
    with pytest.raises(auth.FunctionsHttpError):
        handler.invoke_edge("synthetic")
    assert env.client.functions.invoke.call_count == 1
    env.post.assert_not_called()


@pytest.mark.parametrize("payload,expected", [(b'{"authorized":true}', True), (b'{"authorized":false}', False), (b"invalid json", False), ({"authorized": True}, False)])
def test_bulk_report_permission_fails_closed(auth_environment, payload, expected):
    handler = auth.AuthHandler()
    handler._set_access("access")
    auth_environment.client.functions.invoke.return_value = payload
    assert handler.can_bulk_report() is expected


def test_pkce_challenge_matches_verifier():
    verifier, challenge = auth._pkce_pair()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    assert challenge == expected
    assert 43 <= len(verifier) <= 128
    assert "=" not in verifier


def test_post_json_preserves_payload_headers_and_timeout(monkeypatch):
    response = Mock(status_code=200)
    response.json.return_value = {"accepted": True}
    post = Mock(return_value=response)
    monkeypatch.setattr(auth.requests, "post", post)
    monkeypatch.setattr(auth, "VERCEL_BYPASS", "test-bypass")
    assert auth._post_json("/test", {"value": 4}, timeout=7) == {"accepted": True}
    assert post.call_args.kwargs["timeout"] == 7
    assert post.call_args.kwargs["json"] == {"value": 4}
    assert post.call_args.kwargs["headers"]["x-vercel-protection-bypass"] == "test-bypass"


def test_post_json_http_error_reaches_caller(monkeypatch):
    response = Mock(status_code=401, text="synthetic rejection")
    response.raise_for_status.side_effect = requests.HTTPError("rejected")
    monkeypatch.setattr(auth.requests, "post", Mock(return_value=response))
    with pytest.raises(requests.HTTPError):
        auth._post_json("/test", {})
    response.json.assert_not_called()


def test_unauthenticated_edge_call_raises_typed_unauthorized_error(auth_environment):
    handler = auth.AuthHandler()
    with pytest.raises(auth.FunctionsHttpError) as error:
        handler.invoke_edge("synthetic")
    assert error.value.status == 401
    auth_environment.client.functions.invoke.assert_not_called()


def test_edge_refresh_rejection_logs_out_and_clears_credentials(auth_environment):
    env = auth_environment
    handler = auth.AuthHandler()
    handler._set_access("access", "refresh")
    env.client.functions.invoke.side_effect = auth.FunctionsHttpError("rejected", 401)
    env.post.side_effect = requests.HTTPError("refresh rejected")
    with pytest.raises(auth.FunctionsHttpError):
        handler.invoke_edge("synthetic")
    assert not handler.is_logged_in()
    assert not env.tokens
    assert env.client.functions.invoke.call_count == 1


@pytest.mark.parametrize("payload,expected", [
    (b'{"inPTN":true,"roleKeys":["carrier-owner"]}', (True, ["carrier-owner"])),
    (b'{"inPTN":false}', (False, [])), (b"invalid json", (None, [])),
    ({"inPTN": True}, (None, [])),
])
def test_role_verification_transforms_edge_response(auth_environment, monkeypatch, payload, expected):
    env = auth_environment
    handler = auth.AuthHandler()
    handler._set_access("access")
    transient = Mock(return_value="transient-discord-token")
    monkeypatch.setattr(handler, "_discord_user_token", transient)
    env.client.functions.invoke.return_value = payload
    assert handler.auth_PTN_roles() == expected
    assert env.client.functions.invoke.call_args.kwargs["invoke_options"]["body"] == {"discord_access_token": "transient-discord-token"}
    assert not env.tokens


def test_logged_out_role_checks_fail_closed(auth_environment):
    handler = auth.AuthHandler()
    assert handler.auth_PTN_roles() == (None, [])
    assert handler.can_bulk_report() is False
    auth_environment.client.functions.invoke.assert_not_called()


@pytest.fixture(scope="module")
def signing_key():
    from cryptography.hazmat.primitives.asymmetric import rsa
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def jwt_verifier(monkeypatch, signing_key):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 1, 1, tzinfo=timezone.utc).astimezone(tz)

    jwks_client = SimpleNamespace(get_signing_key_from_jwt=Mock(return_value=SimpleNamespace(key=signing_key.public_key())))
    monkeypatch.setattr(auth, "PyJWKClient", Mock(return_value=jwks_client))
    monkeypatch.setattr(auth.jwt.api_jwt, "datetime", FrozenDateTime)
    response = Mock()
    response.json.return_value = {"keys": []}
    monkeypatch.setattr(auth.requests, "get", Mock(return_value=response))
    return auth.JwtVerifier("https://synthetic.example")


def test_jwt_verifier_validates_signed_identity(jwt_verifier, signing_key):
    claims = {"sub": "123456789012345678", "aud": "authenticated", "iss": "https://synthetic.example/auth/v1", "exp": 1767229200}
    token = auth.jwt.encode(claims, signing_key, algorithm="RS256")
    verified = jwt_verifier.decode_verify(token)
    assert verified["sub"] == claims["sub"]
    assert verified["exp"] == 1767229200


@pytest.mark.parametrize("change", [
    {"aud": "wrong-audience"}, {"iss": "https://wrong.example"}, {"exp": 1}, {"sub": None},
])
def test_jwt_verifier_rejects_invalid_claims(jwt_verifier, signing_key, change):
    claims = {"sub": "123456789012345678", "aud": "authenticated", "iss": "https://synthetic.example/auth/v1", "exp": 1767229200}
    claims.update(change)
    token = auth.jwt.encode(claims, signing_key, algorithm="RS256")
    with pytest.raises(auth.InvalidTokenError):
        jwt_verifier.decode_verify(token)


def test_jwt_verifier_fallback_accepts_valid_jwk(jwt_verifier, signing_key, monkeypatch):
    import json
    claims = {"sub": "123456789012345678", "aud": "authenticated", "iss": "https://synthetic.example/auth/v1", "exp": 1767229200}
    token = auth.jwt.encode(claims, signing_key, algorithm="RS256")
    jwt_verifier._client.get_signing_key_from_jwt.side_effect = ValueError("no matching kid")
    response = Mock()
    response.json.return_value = {"keys": [json.loads(auth.jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key()))]}
    get = Mock(return_value=response)
    monkeypatch.setattr(auth.requests, "get", get)
    assert jwt_verifier.decode_verify(token)["sub"] == claims["sub"]
    assert get.call_args.kwargs["timeout"] == 5
