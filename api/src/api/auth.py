import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from api.db import get_db
from api.models import User

APPLE_KEYS_URL = "https://appleid.apple.com/auth/keys"
APPLE_ISSUER = "https://appleid.apple.com"
# must exactly match the app's bundle identifier as registered in App Store
# Connect once a real Apple Developer account is set up (see mobile/app.json)
APPLE_BUNDLE_ID = "com.declanhogg.trailapp"

# fetches, caches, and matches Apple's public signing keys automatically
# (including key rotation) -- one client instance reused for the life of
# the process rather than one per request
_apple_jwks_client = jwt.PyJWKClient(APPLE_KEYS_URL)

# our OWN session tokens, issued after we've verified an Apple identity
# token once -- these are what the app actually sends on every subsequent
# request, so we're not re-verifying with Apple constantly. Signed with a
# secret only this server knows.
# TODO: move to a real secret from the environment before deploying -- this
# default is only safe for local development (32+ bytes, the minimum HMAC-SHA256 recommends)
SESSION_SECRET = os.environ.get("SESSION_SECRET", "dev-secret-change-me-before-deploying-32b")
SESSION_ALGORITHM = "HS256"
SESSION_EXPIRY = timedelta(days=30)

# lets the app skip real Apple verification during local development, since
# testing Sign in with Apple for real requires a paid Apple Developer
# Program account and a compiled dev build (not just Expo Go). Off by
# default -- must be explicitly opted into for a given local run, and should
# never be enabled anywhere this server is actually reachable by anyone else.
DEV_AUTH_ENABLED = os.environ.get("DEV_AUTH_ENABLED", "false").lower() == "true"
DEV_AUTH_SUB = "dev-bypass-user"


def verify_apple_identity_token(identity_token: str) -> str:
    """Verifies a token Apple issued to the app after Sign in with Apple.
    Returns Apple's stable, unique identifier for this user (the 'sub' claim).
    Raises jwt.PyJWTError (or a subclass) if the token is invalid, expired,
    or wasn't actually issued by Apple for this app."""
    signing_key = _apple_jwks_client.get_signing_key_from_jwt(identity_token)
    claims = jwt.decode(
        identity_token,
        key=signing_key.key,
        algorithms=["RS256"],
        audience=APPLE_BUNDLE_ID,
        issuer=APPLE_ISSUER,
    )
    return claims["sub"]


def get_or_create_user(db: Session, apple_sub: str) -> User:
    user = db.query(User).filter(User.apple_sub == apple_sub).one_or_none()
    if user is None:
        user = User(apple_sub=apple_sub)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def create_session_token(user_id: int) -> str:
    payload = {
        "user_id": user_id,
        # also doubles as the token's own identity for revocation purposes
        # -- see tokens_invalid_before below
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + SESSION_EXPIRY,
    }
    return jwt.encode(payload, SESSION_SECRET, algorithm=SESSION_ALGORITHM)


def revoke_all_sessions(db: Session, user: User) -> None:
    """Invalidates every session token issued for this user up to now,
    including the one making this very request -- called on sign-out so a
    stolen-but-not-yet-expired token can't keep working after the person
    who noticed signs out. A stateless JWT can't be revoked individually,
    so this works by rejecting anything issued before this moment instead
    (see get_current_user's iat check)."""
    # stored naive (see get_current_user's comment on why) -- explicit here
    # rather than relying on SQLite to silently strip tzinfo on the way in
    user.tokens_invalid_before = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()


_bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    try:
        payload = jwt.decode(credentials.credentials, SESSION_SECRET, algorithms=[SESSION_ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="invalid or expired session token")

    user = db.get(User, payload["user_id"])
    if user is None:
        raise HTTPException(status_code=401, detail="user not found")

    if user.tokens_invalid_before is not None:
        # PyJWT decodes "iat" back into a plain int (epoch seconds); SQLite
        # round-trips DateTime columns as naive (tzinfo stripped), so both
        # sides are normalized to naive UTC here rather than risking a
        # "can't compare offset-naive and offset-aware datetimes" crash
        issued_at = datetime.fromtimestamp(payload["iat"], tz=timezone.utc).replace(tzinfo=None)
        if issued_at < user.tokens_invalid_before:
            raise HTTPException(status_code=401, detail="session has been signed out")

    return user
