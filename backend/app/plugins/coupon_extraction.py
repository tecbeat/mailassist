"""Coupon extraction AI plugin.

Extracts discount codes, promo codes, and voucher codes from emails.
Stores extracted coupons in the database and triggers notifications.
Runs fifth in the pipeline (execution_order=50).
"""

import re

from pydantic import BaseModel, Field, field_validator

from app.plugins.base import AIFunctionPlugin, ActionResult, MailContext
from app.plugins.registry import register_plugin


class Coupon(BaseModel):
    """A single extracted coupon or promotional offer."""

    code: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=300)
    expires_at: str | None = None
    valid_from: str | None = None
    store: str | None = Field(default=None, max_length=200)

    @field_validator("expires_at", "valid_from", mode="before")
    @classmethod
    def validate_date_format(cls, v: str | None) -> str | None:
        """Ensure date fields are valid YYYY-MM-DD, discard otherwise."""
        if v is None:
            return None
        v = v.strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            return v
        # Non-ISO date string from LLM — discard silently
        return None


class CouponExtractionResponse(BaseModel):
    """Validated LLM response for coupon extraction."""

    has_coupons: bool
    coupons: list[Coupon] = Field(default_factory=list, max_length=20)


@register_plugin
class CouponExtractionPlugin(AIFunctionPlugin[CouponExtractionResponse]):
    """Extract discount codes, promo codes, and voucher codes from emails."""

    name = "coupon_extraction"
    display_name = "Coupon Extraction"
    description = "Finds and stores discount codes, promo codes, and voucher codes"
    default_prompt_template = "prompts/coupon_extraction.j2"
    execution_order = 50
    icon = "Ticket"
    approval_key = "coupon"
    has_view_page = True
    view_route = "/coupons"

    async def execute(self, context: MailContext, ai_response: CouponExtractionResponse) -> ActionResult:
        if not ai_response.has_coupons or not ai_response.coupons:
            return self._no_action("no_coupons_found")

        actions: list[str] = ["apply_label:coupon"]

        for coupon in ai_response.coupons:
            store = coupon.store or "Unknown"
            label = coupon.code or coupon.description or "Promotion"
            actions.append(f"store_coupon:{label} ({store})")

        self.logger.info(
            "coupons_extracted",
            count=len(ai_response.coupons),
            mail_uid=context.mail_uid,
        )

        return ActionResult(
            success=True,
            actions_taken=actions,
        )

    def get_approval_summary(self, ai_response: CouponExtractionResponse) -> str:
        labels = [c.code or c.description or "Promotion" for c in ai_response.coupons]
        return f"Found {len(labels)} coupon(s): {', '.join(labels)}"
