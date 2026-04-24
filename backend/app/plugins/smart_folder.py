"""Smart Folder AI plugin.

Moves emails to appropriate IMAP folders based on AI analysis.
Prefers existing folders, creates new ones (including nested) only when necessary.
Tracks new folders in FolderChangeLog for re-processing.
"""

from pydantic import BaseModel, Field

from app.plugins.base import AIFunctionPlugin, ActionResult, MailContext
from app.plugins.registry import register_plugin


class SmartFolderResponse(BaseModel):
    """Validated LLM response for smart folder assignment."""

    folder: str = Field(max_length=200)
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(max_length=200)


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
    default_config = {"confidence_threshold": 0.7}

    async def execute(self, context: MailContext, ai_response: SmartFolderResponse) -> ActionResult:
        folder = ai_response.folder

        excluded_set = {f.lower() for f in context.excluded_folders}

        # Hard guard: if the AI suggests an excluded folder, force approval
        # so the user can override. This should rarely trigger because
        # excluded folders are already filtered from the prompt.
        if folder.lower() in excluded_set:
            self.logger.warning(
                "smart_folder_excluded_folder_suggested",
                folder=folder,
                mail_uid=context.mail_uid,
            )
            return ActionResult(
                success=True,
                actions_taken=[],
                requires_approval=True,
                approval_summary=f"AI suggested excluded folder '{folder}': {ai_response.reason}",
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
