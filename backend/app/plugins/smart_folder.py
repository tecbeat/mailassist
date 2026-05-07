"""Smart Folder AI plugin.

Moves emails to appropriate IMAP folders based on AI analysis.
Prefers existing folders, creates new ones (including nested) only when necessary.
Tracks new folders in FolderChangeLog for re-processing.
"""

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from app.plugins.base import ActionResult, AIFunctionPlugin, MailContext
from app.plugins.registry import register_plugin


class SmartFolderResponse(BaseModel):
    """Validated LLM response for smart folder assignment."""

    folder: str = Field(max_length=200)
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(max_length=200)


class ExcludedFolderError(Exception):
    """Raised when the AI repeatedly suggests an excluded folder."""


@register_plugin
class SmartFolderPlugin(AIFunctionPlugin[SmartFolderResponse]):
    """Assign emails to IMAP folders using AI analysis."""

    name = "smart_folder"
    display_name = "Smart Folders"
    description = "Moves emails to appropriate folders based on content analysis, preferring existing folders"
    default_prompt_template = "prompts/smart_folder.j2"
    execution_order = 40
    icon = "FolderTree"
    approval_key = "smart_folder"
    has_view_page = True
    view_route = "/smart-folders"
    default_config: ClassVar[dict[str, Any]] = {"confidence_threshold": 0.7}

    async def execute(self, context: MailContext, ai_response: SmartFolderResponse) -> ActionResult:
        folder = ai_response.folder

        excluded_set = {f.lower() for f in context.excluded_folders}

        # Guard: if the AI suggests an excluded folder, request a reprompt.
        # The executor will re-call the LLM with the corrective prompt and
        # invoke execute() again. On the second violation we raise an error.
        if folder.lower() in excluded_set:
            is_retry = getattr(self, "_excluded_retry_done", False)

            if is_retry:
                self.logger.error(
                    "smart_folder_excluded_folder_repeated",
                    folder=folder,
                    mail_uid=context.mail_uid,
                )
                raise ExcludedFolderError(f"AI suggested excluded folder '{folder}' twice despite corrective prompt")

            self.logger.info(
                "smart_folder_excluded_folder_reprompt",
                folder=folder,
                mail_uid=context.mail_uid,
            )
            self._excluded_retry_done = True
            existing = ", ".join(context.existing_folders) if context.existing_folders else "(no existing folders)"
            return ActionResult(
                success=True,
                actions_taken=[],
                retry_prompt=(
                    f"The folder '{folder}' is not allowed. "
                    f"Choose a different folder from the existing list: {existing}. "
                    "Respond with the same JSON format."
                ),
            )

        # Reset retry flag on successful (non-excluded) suggestion
        self._excluded_retry_done = False

        # INBOX fallback: the AI couldn't determine a better folder — move to INBOX
        if folder.upper() == "INBOX":
            self.logger.info(
                "smart_folder_inbox_fallback",
                mail_uid=context.mail_uid,
                reason=ai_response.reason,
            )
            return ActionResult(
                success=True,
                actions_taken=["move_to:INBOX"],
            )

        existing_set = {f.lower() for f in context.existing_folders}
        is_new_folder = folder.lower() not in existing_set

        # Below confidence threshold: always require approval
        threshold: float = self.get_config("confidence_threshold")
        if not self._meets_threshold(ai_response.confidence, threshold):
            return ActionResult(
                success=True,
                actions_taken=[],
                requires_approval=True,
                approval_summary=self.get_approval_summary(ai_response),
            )

        actions: list[str] = []

        if is_new_folder:
            actions.append(f"create_folder:{folder}")
            actions.append(f"log_new_folder:{folder}")
            self.logger.info(
                "new_folder_created",
                folder=folder,
                mail_uid=context.mail_uid,
            )

        actions.append(f"move_to:{folder}")

        return ActionResult(
            success=True,
            actions_taken=actions,
        )

    def get_approval_summary(self, ai_response: SmartFolderResponse) -> str:
        return f"Move to '{ai_response.folder}' (confidence: {ai_response.confidence:.0%}): {ai_response.reason}"
