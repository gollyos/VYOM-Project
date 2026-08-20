from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable

from .diagram_engine import DiagramSpec
from .export_manager import ArtifactStore, VersionManager
from .presentation_builder import SlideDeckSpec
from .renderer import ArtifactRenderer, ArtifactUnavailableError
from .schemas import ArtifactRecord, ArtifactSpec, ArtifactStatus
from .spreadsheet_builder import SpreadsheetSpec
from .validator import ArtifactValidator, ValidationReport

EmitFn = Callable[[str, str, dict[str, Any]], Awaitable[None]]


async def _noop_emit(event_type: str, message: str, payload: dict[str, Any]) -> None:
    return None


class ArtifactEngine:
    """goal -> gather verified data -> create content structure -> generate
    -> render -> inspect -> validate -> repair -> final version -> evidence.

    File creation is never automatically treated as success; every
    create_* method renders through ArtifactRenderer and then runs a real,
    type-specific ArtifactValidator check before the record can be marked
    VALIDATED.
    """

    def __init__(self, output_root: Path, store: ArtifactStore):
        self.renderer = ArtifactRenderer(output_root)
        self.validator = ArtifactValidator()
        self.store = store

    async def create_markdown_report(
        self,
        spec: ArtifactSpec,
        *,
        version: str = "v1",
        previous_versions: list[str] | None = None,
        record_id: str | None = None,
        emit: EmitFn | None = None,
    ) -> ArtifactRecord:
        emit = emit or _noop_emit
        record = ArtifactRecord(id=record_id or spec.id, spec=spec, version=version, versions=list(previous_versions or []))
        await emit("artifact_started", f"Generating {spec.type.value} artifact: {spec.title}", {"artifact_id": record.id, "version": version})

        path = self.renderer.render_markdown_file(spec, version)
        record.output_path = str(path)
        record.status = ArtifactStatus.RENDERED
        await emit("artifact_rendered", f"Rendered {spec.title}", {"artifact_id": record.id, "path": str(path)})

        report = self.validator.validate_markdown(spec, path)
        record = await self._apply_validation(record, report, emit)
        await self.store.save(record)
        return record

    async def create_diagram(self, spec: ArtifactSpec, diagram_spec: DiagramSpec, *, version: str = "v1", emit: EmitFn | None = None) -> ArtifactRecord:
        emit = emit or _noop_emit
        record = ArtifactRecord(id=spec.id, spec=spec, version=version)
        await emit("artifact_started", f"Generating diagram: {spec.title}", {"artifact_id": record.id})
        path = self.renderer.render_diagram_file(spec, version, diagram_spec)
        record.output_path = str(path)
        record.status = ArtifactStatus.RENDERED
        await emit("artifact_rendered", f"Rendered diagram {spec.title}", {"artifact_id": record.id, "path": str(path)})
        report = self.validator.validate_diagram(diagram_spec, path)
        record = await self._apply_validation(record, report, emit)
        await self.store.save(record)
        return record

    async def create_spreadsheet(self, spec: ArtifactSpec, spreadsheet: SpreadsheetSpec, *, version: str = "v1", emit: EmitFn | None = None) -> ArtifactRecord:
        emit = emit or _noop_emit
        record = ArtifactRecord(id=spec.id, spec=spec, version=version)
        await emit("artifact_started", f"Generating spreadsheet: {spec.title}", {"artifact_id": record.id})
        try:
            path = self.renderer.render_spreadsheet_file(spec, version, spreadsheet)
        except ArtifactUnavailableError as error:
            return await self._fail(record, str(error), emit)
        record.output_path = str(path)
        record.status = ArtifactStatus.RENDERED
        await emit("artifact_rendered", f"Rendered spreadsheet {spec.title}", {"artifact_id": record.id, "path": str(path)})
        report = self.validator.validate_spreadsheet(path, spreadsheet)
        record = await self._apply_validation(record, report, emit)
        await self.store.save(record)
        return record

    async def create_presentation(self, spec: ArtifactSpec, deck: SlideDeckSpec, *, version: str = "v1", emit: EmitFn | None = None) -> ArtifactRecord:
        emit = emit or _noop_emit
        record = ArtifactRecord(id=spec.id, spec=spec, version=version)
        await emit("artifact_started", f"Generating presentation: {spec.title}", {"artifact_id": record.id})
        try:
            path = self.renderer.render_presentation_file(spec, version, deck)
        except ArtifactUnavailableError as error:
            return await self._fail(record, str(error), emit)
        record.output_path = str(path)
        record.status = ArtifactStatus.RENDERED
        await emit("artifact_rendered", f"Rendered presentation {spec.title}", {"artifact_id": record.id, "path": str(path)})
        report = self.validator.validate_presentation(path, deck)
        record = await self._apply_validation(record, report, emit)
        await self.store.save(record)
        return record

    async def revise_markdown_report(self, previous: ArtifactRecord, new_spec: ArtifactSpec, *, emit: EmitFn | None = None) -> ArtifactRecord:
        """Repair/regenerate content into a new version. The previous
        version's file is left untouched under its own version directory."""
        next_version = VersionManager.next_version([*previous.versions, previous.version])
        previous_versions = [*previous.versions, previous.version] if previous.version not in previous.versions else list(previous.versions)
        return await self.create_markdown_report(
            new_spec, version=next_version, previous_versions=previous_versions, record_id=previous.id, emit=emit,
        )

    def mark_final(self, record: ArtifactRecord) -> ArtifactRecord:
        return VersionManager.mark_final(record)

    async def _fail(self, record: ArtifactRecord, message: str, emit: EmitFn) -> ArtifactRecord:
        record.status = ArtifactStatus.FAILED
        record.validation_errors = [message]
        await emit("artifact_validation_failed", message, {"artifact_id": record.id})
        await self.store.save(record)
        return record

    async def _apply_validation(self, record: ArtifactRecord, report: ValidationReport, emit: EmitFn) -> ArtifactRecord:
        record.validation_errors = report.errors
        if report.valid:
            record.status = ArtifactStatus.VALIDATED
            record.verified = True
            await emit("artifact_verified", f"Artifact validated: {record.spec.title}", {"artifact_id": record.id})
        else:
            record.status = ArtifactStatus.FAILED
            record.verified = False
            await emit("artifact_validation_failed", f"Validation failed for {record.spec.title}", {"artifact_id": record.id, "errors": report.errors})
        return record
