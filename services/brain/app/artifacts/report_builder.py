from __future__ import annotations

from .schemas import ArtifactSpec, ArtifactType, ContentSection
from .templates import build_report_sections


class ReportBuilder:
    """Professional reports: executive summary, findings, data,
    recommendations, risks, evidence/sources, next actions."""

    def build(
        self,
        *,
        title: str,
        purpose: str,
        audience: str,
        executive_summary: str,
        findings: list[str],
        data_notes: str,
        recommendations: list[str],
        risks: list[str],
        evidence: list[str],
        next_actions: list[str],
        data_sources: list[str],
        task_id: str | None = None,
    ) -> ArtifactSpec:
        sections = build_report_sections({
            "Executive Summary": ContentSection(heading="Executive Summary", body=executive_summary),
            "Findings": ContentSection(heading="Findings", bullets=findings),
            "Data": ContentSection(heading="Data", body=data_notes),
            "Recommendations": ContentSection(heading="Recommendations", bullets=recommendations),
            "Risks": ContentSection(heading="Risks", bullets=risks),
            "Evidence / Sources": ContentSection(heading="Evidence / Sources", bullets=evidence),
            "Next Actions": ContentSection(heading="Next Actions", bullets=next_actions),
        })
        return ArtifactSpec(
            type=ArtifactType.MARKDOWN,
            title=title,
            purpose=purpose,
            audience=audience,
            content_sections=sections,
            data_sources=data_sources,
            task_id=task_id,
            verification_requirements=["required_sections", "sources_present"],
        )
