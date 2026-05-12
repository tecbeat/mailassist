"""OTP code extraction AI plugin.

Extracts one-time passwords, 2FA codes, verification codes, and magic link
tokens from emails. Stores extracted codes in the database for quick access.
Runs fourth in the pipeline (execution_order=45).
"""

from typing import Any

import structlog
from pydantic import BaseModel, Field, field_validator

from app.plugins.base import ActionResult, AIFunctionPlugin, MailContext
from app.plugins.registry import register_plugin

logger = structlog.get_logger()


class OtpCode(BaseModel):
    """A single extracted OTP or verification code."""

    code: str = Field(max_length=2000)
    description: str | None = Field(default=None, max_length=500)
    service: str | None = Field(default=None, max_length=100)
    code_type: str = Field(max_length=30)
    expires_in_minutes: int | None = None
    url: str | None = Field(default=None, max_length=2000)

    @field_validator("code_type")
    @classmethod
    def validate_code_type(cls, v: str) -> str:
        allowed = {"otp", "2fa", "verification", "login", "magic_link", "other"}
        v = v.strip().lower()
        if v not in allowed:
            return "other"
        return v

    @field_validator("expires_in_minutes")
    @classmethod
    def clamp_expiry(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if v <= 0:
            return None
        return min(v, 1440)


class OtpExtractionResponse(BaseModel):
    """Validated LLM response for OTP extraction."""

    has_codes: bool
    codes: list[OtpCode] = Field(default_factory=list, max_length=10)


@register_plugin
class OtpExtractionPlugin(AIFunctionPlugin[OtpExtractionResponse]):
    """Extract OTP, 2FA, verification codes and magic link tokens from emails."""

    name = "otp_extraction"
    display_name = "OTP Extraction"
    description = "Extracts one-time passwords and verification codes from emails"
    default_prompt_template = "prompts/otp_extraction.j2"
    execution_order = 45
    icon = "KeyRound"
    approval_key = "otp"
    has_view_page = True
    view_route = "/otp-codes"
    notification_event_type = "otp_found"
    notification_template = "notifications/otp_found.j2"

    async def execute(self, context: MailContext, ai_response: OtpExtractionResponse) -> ActionResult:
        if not ai_response.has_codes or not ai_response.codes:
            return self._no_action("no_otp_found")

        actions: list[str] = []
        for code in ai_response.codes:
            svc = code.service or "Unknown"
            actions.append(f"store_otp:{code.code} ({svc})")

        self.logger.info(
            "otp_extracted",
            count=len(ai_response.codes),
            mail_uid=context.mail_uid,
        )

        return ActionResult(
            success=True,
            actions_taken=actions,
        )

    def get_approval_summary(self, ai_response: OtpExtractionResponse) -> str:
        labels = [f"{c.code_type} from {c.service or 'Unknown'}" for c in ai_response.codes]
        return f"Found {len(labels)} OTP code(s): {', '.join(labels)}"

    @classmethod
    async def load_notification_context(
        cls,
        db: Any,
        account_id: Any,
        mail_uid: str,
        *,
        mail_id: Any = None,
    ) -> dict[str, Any]:
        """Load OTP data from the database for notification context.

        Returns flat variables for the first (and typically only) OTP in the mail.
        """
        from sqlalchemy import select

        from app.models.mail import ExtractedOtpCode

        if mail_id is None:
            logger.warning(
                "load_notification_context called without mail_id",
                plugin="otp_extraction",
                account_id=str(account_id),
                mail_uid=mail_uid,
            )
            return {}
        stmt = select(ExtractedOtpCode).where(ExtractedOtpCode.mail_id == mail_id)
        result = await db.execute(stmt)
        otp_codes = result.scalars().all()
        if not otp_codes:
            return {}
        otp = otp_codes[0]
        return {
            "otp_code": otp.code,
            "otp_service": otp.service or "",
            "otp_description": otp.description or "",
            "otp_code_type": otp.code_type,
            "otp_url": otp.url or "",
        }

    @classmethod
    def get_notification_variables(cls) -> list[dict[str, Any]]:
        return [
            {
                "name": "otp_code",
                "var_type": "String",
                "description": "The extracted OTP / verification code",
                "example": "482937",
            },
            {
                "name": "otp_service",
                "var_type": "String",
                "description": "Service or app the code belongs to",
                "example": "GitHub",
            },
            {
                "name": "otp_description",
                "var_type": "String",
                "description": "Short description of the code purpose",
                "example": "Login verification code",
            },
            {
                "name": "otp_code_type",
                "var_type": "String",
                "description": "Code type (otp, 2fa, verification, login, magic_link, other)",
                "example": "2fa",
            },
            {
                "name": "otp_url",
                "var_type": "String",
                "description": "Magic link URL associated with the code (if any)",
                "example": "https://example.com/verify?token=abc123",
            },
        ]

    @classmethod
    def get_preview_context(cls) -> dict[str, Any]:
        return {
            "otp_code": "482937",
            "otp_service": "GitHub",
            "otp_description": "Login verification code",
            "otp_code_type": "2fa",
            "otp_url": "",
        }
