"""OTP code extraction AI plugin.

Extracts one-time passwords, 2FA codes, verification codes, and magic link
tokens from emails. Stores extracted codes in the database for quick access.
Runs fourth in the pipeline (execution_order=45).
"""

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
