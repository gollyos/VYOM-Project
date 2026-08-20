from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any

# Defuddle integration (Phase 13.5), based on the Defuddle capability
# from kepano/obsidian-skills (MIT): clean, readable static-webpage
# extraction to Markdown-like text. This is a self-contained stdlib
# implementation of that capability — no npm dependency is added, so
# VYOM keeps working if Defuddle is absent or disabled. JS/login-heavy
# pages fall back to the existing Playwright Browser Agent.


@dataclass
class PageClassification:
    static_readable: bool
    reasons: list[str] = field(default_factory=list)


@dataclass
class ExtractionResult:
    url: str
    title: str = ""
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    extraction_method: str = "defuddle"
    retrieved_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    success: bool = False
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url, "title": self.title, "content": self.content,
            "metadata": self.metadata, "extraction_method": self.extraction_method,
            "retrieved_at": self.retrieved_at, "success": self.success,
            "warnings": self.warnings,
        }


class _ReadableHTMLParser(HTMLParser):
    """Collects title/meta and the largest coherent block of paragraph
    text (readability heuristic), dropping nav/aside/script/style
    noise. Content between <body> markers only."""

    SKIP = {"script", "style", "nav", "aside", "footer", "header", "noscript", "svg", "form"}
    BLOCK = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "td"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta: dict[str, str] = {}
        self.blocks: list[tuple[int, str]] = []
        self._skip_depth = 0
        self._current: list[str] = []
        self._current_len = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            attributes = dict(attrs)
            name = attributes.get("name") or attributes.get("property") or ""
            if name and attributes.get("content"):
                self.meta[name] = attributes["content"]
        elif tag in self.BLOCK:
            self._flush()

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in self.BLOCK:
            self._flush()

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if self._skip_depth:
            return
        stripped = data.strip()
        if stripped:
            self._current.append(stripped)
            self._current_len += len(stripped)

    def _flush(self):
        if self._current:
            self.blocks.append((self._current_len, " ".join(self._current)))
            self._current, self._current_len = [], 0

    def finish(self) -> tuple[str, dict, str]:
        self._flush()
        # Keep blocks covering ~90% of the coherent text, dropping
        # link-farm/boilerplate tails heuristically.
        total = sum(length for length, _ in self.blocks) or 1
        kept, accumulated = [], 0
        for length, text in sorted(self.blocks, key=lambda b: -b[0]):
            kept.append(text)
            accumulated += length
            if accumulated / total >= 0.9:
                break
        content = "\n\n".join(kept)
        return self.title.strip(), self.meta, content


class DefuddleExtractor:
    """Static-page extractor + page classifier + fallback router.
    `fetch` is pluggable so tests use fixtures and production can use
    any HTTP client already available; the browser fallback is VYOM's
    existing Playwright Browser Agent, launched ONLY when needed."""

    JS_MARKERS = ("reactroot", "__next", "data-react", "ng-app", "vue-app", "id=\"app\"", "data-spa")
    LOGIN_MARKERS = ("sign in", "log in", "password", "create account")

    def __init__(self, fetch=None, browser_fallback=None, learner=None):
        self.fetch = fetch            # async (url) -> str html
        self.browser_fallback = browser_fallback  # async (url) -> ExtractionResult
        self.learner = learner        # Phase 14 AdaptiveLearner — records outcomes;
        # when present, selection LEARNS from history (Defuddle vs Playwright).

    @staticmethod
    def classify(html: str) -> PageClassification:
        lowered = html.lower()
        reasons: list[str] = []
        if any(marker in lowered for marker in DefuddleExtractor.JS_MARKERS):
            reasons.append("page shell looks JavaScript-rendered")
        if len(re.sub(r"<[^>]+>", "", html).strip()) < 200:
            reasons.append("very little server-rendered text (dynamic content likely)")
        if "window.location" in lowered and "login" in lowered:
            reasons.append("login redirect detected")
        return PageClassification(static_readable=not reasons, reasons=reasons)

    @staticmethod
    def extract_from_html(url: str, html: str) -> ExtractionResult:
        parser = _ReadableHTMLParser()
        parser.feed(html)
        title, meta, content = parser.finish()
        warnings = []
        if len(content) < 120:
            warnings.append("extracted content is very short; a browser fallback may be needed")
        return ExtractionResult(
            url=url, title=title, content=content, metadata=meta,
            success=bool(content), warnings=warnings,
        )

    async def extract(self, url: str) -> ExtractionResult:
        """LEARNED Defuddle-first routing (Phase 17): selection consults
        Phase 14 experience when available — historically-successful
        Defuddle on static pages, Playwright after Defuddle failures on
        JS-heavy pages — and every outcome is recorded so the NEXT
        selection learns from it. Static/readable pages extract here;
        JS/login/dynamic pages (or extraction failure) fall back to the
        Playwright Browser Agent. Never claims browser verification for
        a Defuddle extraction."""
        site_type = self.site_type_for(url)
        prefer_browser = False
        if self.learner is not None:
            try:
                from app.adaptive.learned_router import LearnedRouter

                router = LearnedRouter(self.learner)
                choice = await router.preferred_tool(
                    ["defuddle", "playwright-browser-agent"], {"site_type": site_type})
                prefer_browser = choice.tool == "playwright-browser-agent"
                result = await self._extract_and_learn(url, site_type, prefer_browser)
                return result
            except Exception:
                pass  # learning never blocks extraction
        return await self._extract_and_learn(url, site_type, prefer_browser)

    @staticmethod
    def site_type_for(url: str) -> str:
        """Cheap deterministic pre-classification used as the learning
        condition (refined by the actual page classification)."""
        lowered = (url or "").lower()
        if any(marker in lowered for marker in ("app.", "dashboard", "docs.google", "login", "signin", "/app", "spa")):
            return "js_heavy"
        return "static"

    async def _extract_and_learn(self, url: str, site_type: str, prefer_browser: bool) -> ExtractionResult:
        if prefer_browser and self.browser_fallback is not None:
            result = await self._fallback(url, ["learned preference: playwright for this site type"])
            await self._record(url, site_type, result)
            return result
        result = await self._extract_static_first(url, site_type)
        await self._record(url, site_type, result)
        return result

    async def _extract_static_first(self, url: str, site_type: str) -> ExtractionResult:
        if self.fetch is None:
            return ExtractionResult(url=url, success=False,
                                    warnings=["no fetch backend configured"], extraction_method="defuddle")
        try:
            html = await self.fetch(url)
        except Exception as error:
            return await self._fallback(url, [f"static fetch failed: {error}"])
        classification = self.classify(html)
        if not classification.static_readable:
            return await self._fallback(url, classification.reasons)
        result = self.extract_from_html(url, html)
        if not result.success or "very short" in " ".join(result.warnings):
            if self.browser_fallback is not None:
                return await self._fallback(url, result.warnings or ["weak static extraction"])
        return result

    async def _record(self, url: str, site_type: str, result: ExtractionResult) -> None:
        """Feeds the real outcome into Phase 14 learning."""
        if self.learner is None:
            return
        try:
            from app.adaptive import Experience
            from app.adaptive.experience_store import fingerprint

            await self.learner.store.record(Experience(
                task_type="web_extract",
                task_fingerprint=fingerprint(f"extract {url}"),
                goal=f"Extract content from {url}", domain="research",
                environment={"site_type": site_type},
                tools_used=[result.extraction_method],
                result_summary=f"{result.extraction_method}: {'ok' if result.success else 'failed'}",
                success=result.success,
                verification_score=0.7 if result.success and result.extraction_method == "defuddle" else 0.5,
                conditions={"site_type": site_type},
            ))
        except Exception:
            pass

    async def _fallback(self, url: str, reasons: list[str]) -> ExtractionResult:
        if self.browser_fallback is None:
            return ExtractionResult(url=url, success=False,
                                    warnings=reasons + ["no browser fallback configured"],
                                    extraction_method="defuddle")
        result = await self.browser_fallback(url)
        result.warnings = [f"defuddle fallback ({'; '.join(reasons)})"] + result.warnings
        return result
