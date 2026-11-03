"""Send account mail as Memplug. The From address is never a personal inbox."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.config import mail_from, smtp_host, smtp_password, smtp_port, smtp_username

log = logging.getLogger("memplug.mail")


class MailError(RuntimeError):
    """The message could not be handed to the mail server."""


def send_signin_code(email: str, code: str) -> None:
    send_mail(
        email,
        "Your Memplug sign-in code",
        (
            f"Your Memplug sign-in code is {code}.\n\n"
            "It expires in 10 minutes. If you did not try to sign in, you can ignore this message.\n"
        ),
    )


def send_reset_code(email: str, code: str) -> None:
    send_mail(
        email,
        "Reset your Memplug password",
        (
            f"Your Memplug password reset code is {code}.\n\n"
            "It expires in 10 minutes. If you did not ask to reset your password, you can ignore this message.\n"
        ),
    )


def send_mail(to: str, subject: str, body: str) -> None:
    host = smtp_host()
    if not host:
        raise MailError("email is not configured")
    message = EmailMessage()
    message["From"] = mail_from()
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    try:
        with smtplib.SMTP(host, smtp_port(), timeout=20) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            username = smtp_username()
            if username:
                smtp.login(username, smtp_password())
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        log.exception("mail was not sent")
        raise MailError("email was not sent") from exc
    log.info("mail sent subject=%s", subject)
