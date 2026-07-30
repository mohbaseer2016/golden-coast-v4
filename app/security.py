from passlib.context import CryptContext
from itsdangerous import URLSafeSerializer, BadSignature
from fastapi import Request, HTTPException

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
serializer = URLSafeSerializer("CHANGE_THIS_SECRET_BEFORE_PRODUCTION", salt="golden-coast-session")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)


def set_session(response, user):
    token = serializer.dumps({
        "username": user.username,
        "name": user.name,
        "role": user.role,
        "driver_code": user.driver_code or "",
    })
    response.set_cookie(
        "gc_session",
        token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 12,
    )


def clear_session(response):
    response.delete_cookie("gc_session")


def get_session_user(request: Request):
    token = request.cookies.get("gc_session")
    if not token:
        return None
    try:
        return serializer.loads(token)
    except BadSignature:
        return None


def require_user(request: Request):
    user = get_session_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="انتهت الجلسة. سجل الدخول مرة أخرى.")
    return user


def require_role(request: Request, roles: list[str]):
    user = require_user(request)
    if user["role"] not in roles:
        raise HTTPException(status_code=403, detail="ليس لديك صلاحية.")
    return user
