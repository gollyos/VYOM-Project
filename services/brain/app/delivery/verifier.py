from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .package_builder import DeliveryApprovalStatus, DeliveryPackage


@dataclass
class DeliveryVerificationReport:
    verified: bool
    evidence: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)


class DeliveryVerifier:
    """After sending/uploading, verify the real provider result. A 'send'
    click alone is never delivery evidence."""

    def verify(self, package: DeliveryPackage, provider_response: dict[str, Any]) -> DeliveryVerificationReport:
        has_message_id = bool(provider_response.get("message_id"))
        has_upload_url = bool(provider_response.get("upload_url"))
        has_confirmation = bool(provider_response.get("provider_confirmation"))
        has_timestamp = bool(provider_response.get("timestamp"))
        verified = (has_message_id or has_upload_url) and has_confirmation and has_timestamp

        reasons = []
        if not (has_message_id or has_upload_url):
            reasons.append("No message ID or upload URL returned")
        if not has_confirmation:
            reasons.append("No provider confirmation returned")
        if not has_timestamp:
            reasons.append("No delivery timestamp returned")

        if verified:
            package.approval_status = DeliveryApprovalStatus.SENT
            package.evidence.append(str(provider_response))
        return DeliveryVerificationReport(verified=verified, evidence=provider_response, reasons=reasons)
