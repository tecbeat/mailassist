"""Centralized constants shared across modules.

Avoids divergence bugs caused by maintaining multiple copies of the
same lookup table in different files.
"""

# The 8 pipeline plugin names that run through the LLM pipeline,
# in execution order. Keep in sync with the plugin registry.
PIPELINE_PLUGIN_NAMES: list[str] = [
    "spam_detection",
    "newsletter_detection",
    "labeling",
    "smart_folder",
    "coupon_extraction",
    "calendar_extraction",
    "auto_reply",
    "email_summary",
    "contacts",
]

# Maps plugin registry names to UserSettings approval_mode column names.
# Used by the mail processor, pipeline API, and rules engine to resolve
# a user's approval preference for a given plugin.
PLUGIN_TO_APPROVAL_COLUMN: dict[str, str] = {
    "rules": "approval_mode_rules",
    "spam_detection": "approval_mode_spam",
    "labeling": "approval_mode_labeling",
    "smart_folder": "approval_mode_smart_folder",
    "newsletter_detection": "approval_mode_newsletter",
    "auto_reply": "approval_mode_auto_reply",
    "coupon_extraction": "approval_mode_coupon",
    "calendar_extraction": "approval_mode_calendar",
    "email_summary": "approval_mode_summary",
    "contacts": "approval_mode_contacts",
    "notifications": "approval_mode_notifications",
}

# ISO 639-1 language code to full English name.
# Used by prompt rendering and the prompt preview API.
LANGUAGE_NAMES: dict[str, str] = {
    "de": "German",
    "en": "English",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "pl": "Polish",
    "ru": "Russian",
    "ja": "Japanese",
    "zh": "Chinese",
    "ko": "Korean",
    "ar": "Arabic",
    "tr": "Turkish",
    "sv": "Swedish",
    "da": "Danish",
    "no": "Norwegian",
    "fi": "Finnish",
    "cs": "Czech",
    "uk": "Ukrainian",
}
