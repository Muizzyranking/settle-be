import logging
import re
from datetime import datetime, timezone
from html import unescape

import httpx
from jinja2 import Environment, FileSystemLoader, TemplateNotFound, select_autoescape

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailService:
    RESEND_API_URL = "https://api.resend.com/emails"
    TEMPLATES_DIR = settings.BASE_DIR / "templates" / "emails"

    def __init__(self) -> None:
        self._env = Environment(
            loader=FileSystemLoader(str(self.TEMPLATES_DIR)),
            autoescape=select_autoescape(["html", "xml"]),
        )

    def _default_context(self) -> dict:
        """
        Variables every template can rely on without the caller passing them —
        mainly for base.html (header/footer/branding). Add fields here as needed;
        wire up the corresponding settings if they don't exist yet.
        """
        return {
            "frontend_url": settings.FRONTEND_URL,
            "year": datetime.now(timezone.utc).year,
        }

    def _render_optional(self, path: str, context: dict) -> str | None:
        try:
            return self._env.get_template(path).render(**context)
        except TemplateNotFound:
            return None

    @staticmethod
    def _strip_html(html: str) -> str:
        """Naive HTML → plain-text conversion, used only when no index.txt exists."""
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.S | re.I)
        text = re.sub(r"<br\s*/?>|</p>|</div>|</h[1-6]>|</tr>", "\n", text, flags=re.I)
        text = re.sub(r"<[^>]+>", "", text)
        text = unescape(text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n[ \t]*\n+", "\n\n", text)
        return text.strip()

    def render(
        self, template: str, context: dict | None = None
    ) -> tuple[str | None, str | None]:
        merged = {**self._default_context(), **(context or {})}
        html = self._render_optional(f"{template}/index.html", merged)
        text = self._render_optional(f"{template}/index.txt", merged)
        if text is None and html is not None:
            text = self._strip_html(html)
        return html, text

    async def send(
        self,
        to: str | list[str],
        subject: str,
        template: str,
        context: dict | None = None,
    ) -> None:
        recipients = [to] if isinstance(to, str) else list(to)

        if not settings.RESEND_API_KEY:
            logger.warning(f"RESEND_API_KEY not set — skipping email to {recipients}")
            return

        try:
            html, text = self.render(template, context or {})
        except Exception:
            logger.exception(
                f"Failed to render email template {template!r} for {recipients}"
            )
            return

        if html is None and text is None:
            logger.error(
                f"No index.html or index.txt found for template {template!r} — skipping email to {recipients}"
            )
            return

        payload = {
            "from": settings.EMAIL_FROM,
            "to": recipients,
            "subject": subject,
            "text": text,
        }
        if html is not None:
            payload["html"] = html

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                res = await client.post(
                    self.RESEND_API_URL,
                    headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                    json=payload,
                )
                res.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning(f"Email to {recipients} failed: {exc}")


email_service = EmailService()
