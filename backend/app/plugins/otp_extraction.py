"""OTP code extraction AI plugin.

Extracts one-time passwords, 2FA codes, verification codes, and magic link
tokens from emails. Stores extracted codes in the database for quick access.
Runs fourth in the pipeline (execution_order=45).
"""

from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.plugins.base import ActionResult, AIFunctionPlugin, MailContext
from app.plugins.registry import register_plugin


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
    def get_notification_context(cls, result_data: dict[str, Any]) -> dict[str, Any]:
        otps = result_data.get("otps", [])
        return {
            "otp_codes": [o.get("code") for o in otps],
            "otps": otps,
        }

    @classmethod
    async def load_notification_context(
        cls,
        db: Any,
        account_id: Any,
        mail_uid: str,
    ) -> dict[str, Any]:
        """Load OTP data from the database for notification context."""
        from sqlalchemy import select

        from app.models.mail import ExtractedOtpCode

        result = await db.execute(
            select(ExtractedOtpCode).where(
                ExtractedOtpCode.mail_account_id == account_id,
                ExtractedOtpCode.mail_uid == mail_uid,
            )
        )
        otp_codes = result.scalars().all()
        return {
            "otp_codes": [c.code for c in otp_codes],
            "otps": [
                {"code": c.code, "description": c.description, "service": c.service, "code_type": c.code_type}
                for c in otp_codes
            ],
        }

    @classmethod
    def get_notification_variables(cls) -> list[dict[str, Any]]:
        return [
            {"name": "otp_codes", "var_type": "List", "description": "Extracted OTP codes", "example": '["482937"]'},
            {
                "name": "otps",
                "var_type": "List",
                "description": "Full OTP objects with code, description, service, code_type",
                "example": '[{"code": "482937", "description": "Login code", "service": "GitHub", "code_type": "2fa"}]',
            },
        ]

    @classmethod
    def get_preview_context(cls) -> dict[str, Any]:
        return {
            "otp_codes": ["482937"],
            "otps": [
                {"code": "482937", "description": "Login verification code", "service": "GitHub", "code_type": "2fa"}
            ],
        }
