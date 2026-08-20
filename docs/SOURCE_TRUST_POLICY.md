# VYOM Source Trust Policy

Not all web pages are equal. `SourceRanker`
(`services/brain/app/research/source_ranker.py`) scores every discovered
source on `trust_score * 0.6 + relevance_score * 0.4`.

## Trust weights by source type

| Source type | Default weight | When it applies |
| --- | --- | --- |
| `official` | 0.95 | The vendor/organization's own site or product docs |
| `government` | 0.95 | Regulator or government publication |
| `documentation` | 0.9 | Official technical documentation/API reference |
| `research_paper` | 0.85 | Primary academic/research publication |
| `database` | 0.75 | Structured reference database |
| `company` | 0.65 | Company blog/press material (secondary to official docs) |
| `news` | 0.55 | Independent news coverage |
| `community` | 0.4 | Forums, community wikis |
| `social` | 0.25 | Social media posts |
| `unknown` | 0.2 | Unclassified source |

Weights are configurable in `config/research.yaml`. A source matching the
plan's `preferred_sources` receives a small additional boost.

## Preference rules by question type

- **Technical question** → official docs / source repository first.
- **Company information** → official company sources, cross-checked against
  at least one independent source when the plan's `source_diversity`
  requires it.
- **Legal/regulatory** → official regulator/government source only.
- **Research claim** → the primary paper where practical, not a secondary
  summary.

## Primary vs. secondary

`SourceRanker` labels `official`, `government`, and `research_paper`
sources `primary_or_secondary="primary"`; everything else is `secondary`.
Synthesis and citations prefer primary sources when trust/relevance are
otherwise comparable.

## What this policy does not do

It does not fabricate a trust score for a source VYOM has not actually
read, and it does not silently substitute a lower-trust source for a
required primary one — a missing primary source becomes a recorded gap
(`ResearchResult.gaps`), not an invented citation.
