"""Webhook simulator: delivers inbound payloads to the bot-under-test's webhook URL."""

from wa_agent_test.simulator.client import DeliveryResult, VerificationResult, WebhookSimulator

__all__ = ["DeliveryResult", "VerificationResult", "WebhookSimulator"]
