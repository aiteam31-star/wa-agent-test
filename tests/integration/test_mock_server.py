"""Mock Graph API on a real local port (what an out-of-process bot would talk to)."""

import httpx
import pytest

from wa_agent_test.mock_graph import CaptureStore, MockGraphServer, create_app

pytestmark = pytest.mark.integration


async def test_real_http_roundtrip() -> None:
    store = CaptureStore()
    async with MockGraphServer(create_app(store=store)) as server:
        assert not server.base_url.endswith(":0")
        async with httpx.AsyncClient() as client:
            ok = await client.post(
                f"{server.base_url}/v21.0/123/messages",
                json={
                    "messaging_product": "whatsapp",
                    "to": "919876543210",
                    "type": "text",
                    "text": {"body": "hello"},
                },
            )
            bad = await client.post(
                f"{server.base_url}/v21.0/123/messages",
                json={
                    "messaging_product": "whatsapp",
                    "to": "919876543210",
                    "type": "text",
                    "text": {"body": "x" * 4097},
                },
            )
    assert ok.status_code == 200 and bad.status_code == 400
    assert len(store.messages_for("919876543210")) == 1
    assert len(store.rejected()) == 1
