# VYOM Artifact Engine

## Purpose

`ArtifactEngine` (`services/brain/app/artifacts/engine.py`) turns verified
information into real, validated professional files. File creation is
never automatically treated as success:

```text
Goal
  -> Gather verified data
  -> Create content structure (ReportBuilder / DiagramSpec / SpreadsheetSpec / SlideDeckSpec)
  -> Generate (ArtifactRenderer)
  -> Render to disk
  -> Inspect / Validate (ArtifactValidator)
  -> Repair (revise_markdown_report, new version) if invalid
  -> Final version (VersionManager)
  -> Evidence (ArtifactStore + artifact_verified event)
```

## Supported types

| Type | Renderer output | Always available |
| --- | --- | --- |
| `markdown` | `report.md` | Yes |
| `json` | `data.json` | Yes |
| `csv` | `table.csv` | Yes |
| `diagram` | `diagram.mmd` (Mermaid) | Yes |
| `docx` | `report.docx` | If `python-docx` is installed |
| `spreadsheet` | `workbook.xlsx` | If `openpyxl` is installed |
| `presentation` | `presentation.pptx` | If `python-pptx` is installed |
| `pdf` | — | Not implemented in Phase 8 |

`config/artifacts.yaml` marks the optional types `auto`: when the
dependency is missing, `ArtifactRenderer` raises `ArtifactUnavailableError`
and the artifact is recorded `FAILED` with the honest reason — it is never
faked as a successful file.

## ArtifactSpec

`id, type, title, purpose, audience, content_sections, data_sources, style,
branding, verification_requirements, output_path, created_by, task_id,
version`. Reports use the reusable `STANDARD_REPORT_SECTIONS` layout
(Executive Summary, Findings, Data, Recommendations, Risks, Evidence /
Sources, Next Actions).

## Diagrams

`DiagramEngine` renders `DiagramSpec` (typed nodes/edges) to real Mermaid
text; content always comes from the structured schema, never from random
positioning. `DiagramEngine.validate` checks every node appears in the
rendered text and every edge references two declared nodes.

## Validation per type

| Type | Check |
| --- | --- |
| Report (markdown) | Required sections present; Sources section present when `data_sources` is set |
| Diagram | All nodes/edges present in rendered text |
| Spreadsheet | Workbook opens with `openpyxl`; every expected sheet name present |
| Presentation | Structural bullet/slide bounds; file opens with `python-pptx`; slide count matches the planned deck (+1 title slide) |
| DOCX | File opens with `python-docx` and has content |
| JSON / CSV | Parses; CSV header row matches expected headers when supplied |

## Versioning

`VersionManager.next_version` computes `v1 -> v2 -> v3 -> ...`; a version is
never silently overwritten — `ArtifactRecord.versions` accumulates prior
labels, and `revise_markdown_report` writes the new version to its own
`data/artifacts/<artifact_id>/<version>/` directory, leaving the previous
version's file on disk. `mark_final` appends the explicit `final` label.

## Client branding

`ArtifactSpec.branding` may carry stored client branding (logo, name,
colors, tone) when available through Phase 6/7 memory. VYOM never invents
brand assets; without stored branding, artifacts use the neutral
professional VYOM style (`config/artifacts.yaml` default).

## Presentation bounds

`PresentationBuilder` caps bullets to 5 per slide and 140 characters per
bullet so generated decks stay narrative, not a text wall.
