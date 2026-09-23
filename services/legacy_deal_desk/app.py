"""The legacy deal desk: a plain, server-rendered, no-API, login-gated app.

Exists for exactly one reason -- to be the system AgentCore Browser has to
log into as the real signed-in broker, because there is no other way in.
No JSON endpoint, no framework, a signed cookie for session state (this is
a mock system for a workshop; the point is the absence of an API, not
production-grade session security).

Deployed as a Lambda Function URL because AgentCore Browser runs inside AWS
and has no route to a participant's laptop -- this cannot be `localhost`.

/sso is the OAuth landing route for Checkpoint 4 / Legacy Portal OAuth: real
per-user 3-legged consent happens upstream via AgentCore Identity's Token
Vault (see backend/confirmation.py), and this route's only job is to verify
the resulting token and turn it into the same session cookie the plain
username/password path already produces below.

WORKSHOP SIMPLIFICATION, called out deliberately (see the walkthrough and
README's Known Limitations): the access token is passed as a `?access_token=`
URL query parameter, because the Harness's built-in Browser tool only has
human-like actions (navigate/click/type) -- there's no way for the model to
set a cookie or header directly. That means the real token can end up in
this Lambda's access logs and in any AgentCore Browser session recording.
In production, mint a short-lived, single-use exchange code instead (the
same pattern already used for price-change approval tokens) and never put
the real bearer token in a URL.
"""
import hashlib
import hmac
import html
import json
import os
import ssl
import time
import urllib.parse
import urllib.request

import boto3
import certifi
from jose import jwk, jwt
from jose.utils import base64url_decode

dynamodb = boto3.resource("dynamodb")

_jwks_cache = None
_jwks_cache_at = 0
_JWKS_TTL_SECONDS = 3600


def _oauth_jwks_url() -> str:
    return f"{os.environ['OAUTH_ISSUER']}/.well-known/jwks.json"


def _get_oauth_jwks() -> dict:
    global _jwks_cache, _jwks_cache_at
    if _jwks_cache is None or (time.time() - _jwks_cache_at) > _JWKS_TTL_SECONDS:
        ctx = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(_oauth_jwks_url(), timeout=5, context=ctx) as resp:
            _jwks_cache = json.loads(resp.read())
            _jwks_cache_at = time.time()
    return _jwks_cache


def _verify_oauth_access_token(access_token: str) -> str | None:
    """Verifies signature, expiry, issuer, and client_id against the
    LegacyOAuthAppClient pool (see infra/stacks/identity_stack.py). Returns
    the token's `username` claim on success, None on any failure -- this
    Lambda never trusts a token it hasn't independently verified itself,
    same trust boundary as backend/auth.py's verify_token()."""
    try:
        headers = jwt.get_unverified_header(access_token)
        jwks = _get_oauth_jwks()
        key_data = next((k for k in jwks["keys"] if k["kid"] == headers.get("kid")), None)
        if key_data is None:
            return None
        public_key = jwk.construct(key_data)
        message, encoded_sig = access_token.rsplit(".", 1)
        signature = base64url_decode(encoded_sig.encode("utf-8"))
        if not public_key.verify(message.encode("utf-8"), signature):
            return None
        claims = jwt.get_unverified_claims(access_token)
        if claims.get("token_use") != "access":
            return None
        if claims.get("exp", 0) < time.time():
            return None
        if claims.get("iss") != os.environ["OAUTH_ISSUER"]:
            return None
        if claims.get("client_id") != os.environ["OAUTH_CLIENT_ID"]:
            return None
        return claims.get("username")
    except Exception:
        return None

_COOKIE_SECRET = os.environ.get("WORKSHOP_SECRET", "changeme")
_COOKIE_NAME = "legacy_session"
_COOKIE_TTL_SECONDS = 900


def _sign(username: str, issued_at: str) -> str:
    msg = f"{username}:{issued_at}".encode()
    return hmac.new(_COOKIE_SECRET.encode(), msg, hashlib.sha256).hexdigest()


def _make_cookie(username: str) -> str:
    issued_at = str(int(time.time()))
    sig = _sign(username, issued_at)
    value = urllib.parse.quote(f"{username}.{issued_at}.{sig}")
    return f"{_COOKIE_NAME}={value}; Path=/; HttpOnly; SameSite=Lax"


def _verify_cookie(cookie_header: str | None) -> str | None:
    if not cookie_header:
        return None
    for part in cookie_header.split(";"):
        part = part.strip()
        if not part.startswith(f"{_COOKIE_NAME}="):
            continue
        raw = urllib.parse.unquote(part[len(_COOKIE_NAME) + 1 :])
        try:
            username, issued_at, sig = raw.split(".", 2)
        except ValueError:
            return None
        if not hmac.compare_digest(sig, _sign(username, issued_at)):
            return None
        if time.time() - int(issued_at) > _COOKIE_TTL_SECONDS:
            return None
        return username
    return None


def _page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>
  body {{ font-family: Georgia, 'Times New Roman', serif; background: #e8e4da; margin: 0; padding: 40px; color: #2b2b2b; }}
  .panel {{ max-width: 640px; margin: 0 auto; background: #fdfcf7; border: 1px solid #999; padding: 32px; box-shadow: 2px 2px 0 #999; }}
  h1 {{ font-size: 20px; border-bottom: 2px solid #444; padding-bottom: 8px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 16px 0; }}
  td, th {{ border: 1px solid #bbb; padding: 6px 10px; text-align: left; font-size: 14px; }}
  th {{ background: #ddd6c0; }}
  input {{ display: block; width: 100%; padding: 8px; margin: 8px 0 16px; font-size: 14px; box-sizing: border-box; }}
  button {{ background: #4a4636; color: #fff; border: none; padding: 10px 18px; font-size: 14px; cursor: pointer; }}
  .warn {{ color: #7a1f1f; font-weight: bold; }}
  .foot {{ margin-top: 24px; font-size: 12px; color: #777; }}
</style></head>
<body><div class="panel">{body}</div></body></html>"""


def _login_page(error: str = "") -> str:
    err_html = f'<p class="warn">{html.escape(error)}</p>' if error else ""
    return _page(
        "CRE Deal Desk -- Sign In",
        f"""<h1>CRE Deal Desk (Legacy)</h1>
{err_html}
<form method="POST" action="/login">
  <label>Username</label>
  <input type="text" name="username" autocomplete="username">
  <label>Password</label>
  <input type="password" name="password" autocomplete="current-password">
  <button type="submit">Sign In</button>
</form>
<div class="foot">Internal system. No API. Deal Desk v3.1</div>""",
    )


def _listing_page(username: str, listing_id: str, listing: dict, record: dict) -> str:
    rr = record.get("rentRoll", {})
    rows = "".join(
        f"<tr><td>{html.escape(k)}</td><td>{html.escape(str(v))}</td></tr>"
        for k, v in rr.items()
    )
    return _page(
        f"Deal Desk -- {listing.get('name', listing_id)}",
        f"""<h1>{html.escape(listing.get('name', listing_id))}</h1>
<p>Signed in as <b>{html.escape(username)}</b> &middot; <a href="/logout">Sign out</a></p>
<h2 style="font-size:15px">Rent Roll Summary</h2>
<table><tr><th>Metric</th><th>Value</th></tr>{rows}</table>
<h2 style="font-size:15px">Concessions</h2>
<p>{html.escape(record.get('concessions', 'None on record.'))}</p>
<h2 style="font-size:15px">Deferred Maintenance</h2>
<p>{html.escape(record.get('deferredMaintenance', 'No open items.'))}</p>
<div class="foot">Internal system. No API. Deal Desk v3.1</div>""",
    )


def _parse_form(event: dict) -> dict:
    body = event.get("body", "") or ""
    if event.get("isBase64Encoded"):
        import base64
        body = base64.b64decode(body).decode("utf-8")
    return {k: v[0] for k, v in urllib.parse.parse_qs(body).items()}


def handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    raw_path = event.get("rawPath", "/")
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    query = event.get("queryStringParameters") or {}

    if method == "POST" and raw_path == "/login":
        form = _parse_form(event)
        username = form.get("username", "")
        password = form.get("password", "")

        creds_table = dynamodb.Table(os.environ["CREDS_TABLE"])
        item = creds_table.get_item(Key={"username": username}).get("Item")

        if not item or item.get("password") != password:
            return {
                "statusCode": 401,
                "headers": {"Content-Type": "text/html; charset=utf-8"},
                "body": _login_page("Invalid username or password."),
            }

        return {
            "statusCode": 302,
            "headers": {
                "Location": "/",
                "Set-Cookie": _make_cookie(username),
                "Content-Type": "text/html; charset=utf-8",
            },
            "body": "",
        }

    if raw_path == "/sso":
        access_token = query.get("access_token", "")
        username = _verify_oauth_access_token(access_token) if access_token else None
        if not username:
            return {
                "statusCode": 401,
                "headers": {"Content-Type": "text/html; charset=utf-8"},
                "body": _login_page("Invalid or expired access token."),
            }
        return {
            "statusCode": 302,
            "headers": {
                "Location": "/",
                "Set-Cookie": _make_cookie(username),
                "Content-Type": "text/html; charset=utf-8",
            },
            "body": "",
        }

    if raw_path == "/logout":
        return {
            "statusCode": 302,
            "headers": {
                "Location": "/",
                "Set-Cookie": f"{_COOKIE_NAME}=; Path=/; Max-Age=0",
            },
            "body": "",
        }

    username = _verify_cookie(headers.get("cookie"))
    if not username:
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "text/html; charset=utf-8"},
            "body": _login_page(),
        }

    listing_id = query.get("listing")
    if not listing_id:
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "text/html; charset=utf-8"},
            "body": _page(
                "Deal Desk -- Home",
                f"<h1>Deal Desk</h1><p>Signed in as <b>{html.escape(username)}</b> &middot; "
                f'<a href="/logout">Sign out</a></p>'
                f"<p>Open a listing with <code>?listing=&lt;id&gt;</code>, e.g. "
                f"<code>?listing=hilliard-commons</code>.</p>",
            ),
        }

    listings_table = dynamodb.Table(os.environ["LISTINGS_TABLE"])
    records_table = dynamodb.Table(os.environ["RECORDS_TABLE"])
    listing = listings_table.get_item(Key={"listingId": listing_id}).get("Item") or {}
    record = records_table.get_item(Key={"listingId": listing_id}).get("Item") or {}

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "text/html; charset=utf-8"},
        "body": _listing_page(username, listing_id, listing, record),
    }
