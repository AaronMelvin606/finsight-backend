from slowapi import Limiter
from starlette.requests import Request


def get_real_ip(request: Request) -> str:
    """Extract client IP from X-Forwarded-For header (Cloud Run / load balancer),
    falling back to the direct connection IP."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host


limiter = Limiter(key_func=get_real_ip)
