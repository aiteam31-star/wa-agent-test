"""Mock Graph API: FastAPI app mimicking POST /{version}/{phone_number_id}/messages.

Captures the bot's outbound replies instead of sending them to Meta.
"""

from wa_agent_test.mock_graph.app import create_app
from wa_agent_test.mock_graph.limits import Limits, LimitSpec, load_limits
from wa_agent_test.mock_graph.server import MockGraphServer
from wa_agent_test.mock_graph.store import CapturedMessage, CaptureStore
from wa_agent_test.mock_graph.validation import Violation, validate_message

__all__ = [
    "CaptureStore",
    "CapturedMessage",
    "LimitSpec",
    "Limits",
    "MockGraphServer",
    "Violation",
    "create_app",
    "load_limits",
    "validate_message",
]
