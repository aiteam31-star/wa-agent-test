"""Reports: one self-contained HTML file (chats shown like WhatsApp) and a Markdown summary."""

from wa_agent_test.report.html import attempt_text, render_report, write_report
from wa_agent_test.report.summary import MARKER, render_summary, write_summary

__all__ = [
    "MARKER",
    "attempt_text",
    "render_report",
    "render_summary",
    "write_report",
    "write_summary",
]
