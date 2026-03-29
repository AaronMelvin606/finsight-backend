import resend
import os
import logging

import sentry_sdk

logger = logging.getLogger(__name__)

FRONTEND_URL = os.getenv(
    "FRONTEND_URL",
    "https://finsightai-dashboard.netlify.app"
)
FROM_EMAIL = "FinSight AI <hello@finsightai.tech>"


def send_password_reset_email(to_email: str, reset_token: str) -> bool:
    """
    Send a branded password reset email via Resend.
    Returns True on success, False on failure.
    Never raises — email failure must not break the API response.
    """
    resend.api_key = os.getenv("RESEND_API_KEY")
    if not resend.api_key:
        logger.error("[EMAIL] RESEND_API_KEY not set")
        return False

    reset_link = f"{FRONTEND_URL}/?token={reset_token}"

    try:
        result = resend.Emails.send({
            "from": FROM_EMAIL,
            "to": [to_email],
            "subject": "Reset your FinSight AI password",
            "html": f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#0A0F1E;
font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center" style="padding:40px 20px;">
      <table width="600" cellpadding="0" cellspacing="0"
             style="max-width:600px;width:100%;">
        <tr><td style="padding-bottom:32px;">
          <span style="color:#4CAF7D;font-size:18px;
                       font-weight:600;">FinSight AI</span>
        </td></tr>
        <tr><td>
          <h1 style="color:#F8FAFC;font-size:24px;font-weight:600;
                     margin:0 0 16px 0;">
            Reset your password
          </h1>
          <p style="color:#94A3B8;font-size:14px;line-height:1.6;
                    margin:0 0 32px 0;">
            We received a request to reset the password for your
            FinSight AI account. Click the button below to set a
            new password. This link expires in 1 hour.
          </p>
          <a href="{reset_link}"
             style="display:inline-block;background:#4CAF7D;
                    color:#ffffff;padding:12px 28px;border-radius:8px;
                    text-decoration:none;font-weight:600;font-size:14px;">
            Reset password
          </a>
          <p style="color:#64748B;font-size:12px;margin:32px 0 0 0;
                    line-height:1.6;">
            If you did not request a password reset, you can safely
            ignore this email. This link expires in 1 hour and can
            only be used once.
          </p>
          <hr style="border:none;border-top:1px solid #1E293B;
                     margin:32px 0;">
          <p style="color:#475569;font-size:11px;margin:0;">
            FinSight AI &middot; Private beta &middot;
            <a href="https://finsightai.tech"
               style="color:#475569;">finsightai.tech</a>
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>""",
            "text": f"""Reset your FinSight AI password

We received a request to reset the password for your account.

Click the link below to set a new password (expires in 1 hour):

{reset_link}

If you did not request this, you can safely ignore this email.

FinSight AI · finsightai.tech
"""
        })
        email_id = result.get("id") if isinstance(result, dict) else None
        if not email_id:
            logger.error(
                f"[EMAIL] Resend returned no email id for {to_email}: {result!r}"
            )
            sentry_sdk.capture_message(
                f"Password reset: Resend send returned unexpected response "
                f"for {to_email}: {result!r}",
                level="error",
            )
            return False
        logger.info(f"[EMAIL] Password reset email sent to {to_email} id={email_id}")
        return True

    except Exception as e:
        logger.error(
            f"[EMAIL] Failed to send reset email to {to_email}: {e}"
        )
        sentry_sdk.capture_exception(e)
        return False
