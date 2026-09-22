"""Cognito login and JWT validation.

This is the real trust boundary the rest of the backend relies on: once
a token passes verify_token(), its `sub` and `cognito:groups` claims are
the REAL, validated identity for that session -- not anything the model
or the client can spoof. confirmation.py and the harness-routing logic
in main.py both depend on this being correct.
"""
import ssl
import time
import urllib.request

import boto3
import certifi
from jose import jwk, jwt
from jose.utils import base64url_decode

import config

_cognito = boto3.client("cognito-idp", region_name=config.AWS_REGION)

_JWKS_URL = (
    f"https://cognito-idp.{config.AWS_REGION}.amazonaws.com/"
    f"{config.COGNITO_USER_POOL_ID}/.well-known/jwks.json"
)
_jwks_cache = None
_jwks_cache_at = 0
_JWKS_TTL_SECONDS = 3600


def _get_jwks():
    global _jwks_cache, _jwks_cache_at
    if _jwks_cache is None or (time.time() - _jwks_cache_at) > _JWKS_TTL_SECONDS:
        # Use certifi's CA bundle explicitly rather than relying on the
        # system default -- some Python builds (notably certain macOS
        # installs) ship without a usable default CA bundle, which
        # otherwise fails with CERTIFICATE_VERIFY_FAILED.
        ctx = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(_JWKS_URL, timeout=5, context=ctx) as resp:
            import json
            _jwks_cache = json.loads(resp.read())
            _jwks_cache_at = time.time()
    return _jwks_cache


class AuthError(Exception):
    pass


def login(username: str, password: str) -> dict:
    """Authenticates against Cognito with USER_PASSWORD_AUTH. Returns the
    raw AuthenticationResult (AccessToken, IdToken, ExpiresIn, ...)."""
    try:
        resp = _cognito.initiate_auth(
            ClientId=config.COGNITO_APP_CLIENT_ID,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": username, "PASSWORD": password},
        )
    except _cognito.exceptions.NotAuthorizedException:
        raise AuthError("Incorrect username or password.")
    return resp["AuthenticationResult"]


def verify_token(access_token: str) -> dict:
    """Verifies a Cognito access token's signature and claims. Returns
    the decoded claims dict (sub, username, cognito:groups, exp, ...) on
    success, or raises AuthError."""
    try:
        headers = jwt.get_unverified_header(access_token)
    except Exception as e:
        raise AuthError(f"Malformed token: {e}")

    jwks = _get_jwks()
    key_data = next((k for k in jwks["keys"] if k["kid"] == headers.get("kid")), None)
    if key_data is None:
        raise AuthError("Token key not found in JWKS.")

    public_key = jwk.construct(key_data)
    message, encoded_sig = access_token.rsplit(".", 1)
    signature = base64url_decode(encoded_sig.encode("utf-8"))
    if not public_key.verify(message.encode("utf-8"), signature):
        raise AuthError("Signature verification failed.")

    claims = jwt.get_unverified_claims(access_token)
    if claims.get("exp", 0) < time.time():
        raise AuthError("Token is expired.")
    if claims.get("token_use") != "access":
        raise AuthError("Not an access token.")
    expected_iss = f"https://cognito-idp.{config.AWS_REGION}.amazonaws.com/{config.COGNITO_USER_POOL_ID}"
    if claims.get("iss") != expected_iss:
        raise AuthError("Unexpected issuer.")

    return claims


def group_for_claims(claims: dict) -> str | None:
    """Returns the caller's real group (investors/brokers) from validated
    claims, or None if they're in neither -- the caller decides what to
    do (reject, or default) rather than this function guessing."""
    groups = claims.get("cognito:groups", [])
    for g in ("investors", "brokers"):
        if g in groups:
            return g
    return None
