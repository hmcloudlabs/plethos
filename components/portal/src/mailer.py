import logging
import smtplib
from email.message import EmailMessage

from config import config

logger = logging.getLogger("mailer")


def send_email(*, to: str, subject: str, body: str) -> None:
    if not config.smtp_host:
        logger.info(f"SMTP not configured, skipping email to {to}: {subject}")
        return

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.smtp_from_address
    message["To"] = to
    message.set_content(body)

    try:
        with smtplib.SMTP(config.smtp_host, config.smtp_port) as smtp:
            smtp.ehlo()
            if smtp.has_extn("starttls"):
                smtp.starttls()
                smtp.ehlo()
            if config.smtp_username:
                smtp.login(config.smtp_username, config.smtp_password)
            smtp.send_message(message)
    except OSError as e:
        logger.warning(f"Failed to send email to {to}: {e}")
        return

    logger.info(f"Sent email to {to}: {subject}")
