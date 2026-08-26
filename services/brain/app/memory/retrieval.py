from __future__ import annotations

import re

from .embeddings import EmbeddingProvider, cosine_similarity
from .relevance import relevance_score
from .schemas import MemoryQuery, MemorySearchResult, VerificationState
from .store import MemoryStore


class MemoryRetriever:
    #: Common words that carry no real subject-matter signal but
    #: routinely co-occur by pure chance ("and", "the", "is", "hai").
    #: Counting them as keyword overlap meant almost ANY two sentences
    #: of reasonable length shared at least one stopword, so
    #: `keyword == 0` (the zero-overlap exclusion filter below) almost
    #: never actually fired - a real production bug: "Gunjan's
    #: preferences and business details" matched an unrelated stale
    #: "Solar System" memory purely because both happened to contain
    #: "and". Excluding these from BOTH query and memory tokenization
    #: makes the overlap check measure real subject-matter agreement.
    _STOPWORDS = frozenset({
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
        "has", "have", "he", "her", "his", "i", "in", "is", "it", "its",
        "of", "on", "or", "our", "s", "she", "that", "the", "their",
        "there", "these", "this", "those", "to", "was", "we", "were",
        "will", "with", "you", "your",
        "hai", "hain", "ka", "ke", "ki", "ko", "me", "mein", "se", "hi",
        "bhi", "aur", "ye", "yeh", "wo", "woh", "tum", "tumhara", "mera",
        "meri", "है", "हैं", "का", "के", "की", "को", "में", "से", "और",
        "भी", "यह", "वह", "तुम", "मेरा", "मेरी",
    })

    def __init__(self, store: MemoryStore, embeddings: EmbeddingProvider):
        self.store = store
        self.embeddings = embeddings

    def _tokenize(self, text: str) -> set[str]:
        return set(re.findall(r"\w+", text.lower(), re.UNICODE)) - self._STOPWORDS

    async def search(self, query: MemoryQuery) -> list[MemorySearchResult]:
        # FTS first: a full-text MATCH finds a decade-old record at any
        # scale in milliseconds; the structured candidate window alone
        # made old records unreachable once newer rows existed. When FTS
        # has no hits (or is unavailable) the structured path stands.
        fts_ids: list[str] | None = None
        if query.text:
            fts_ids = await self.store.search_fts(query.text)
        candidates = await self.store.list(
            types=query.types or None,
            project_id=query.project_id,
            client_id=query.client_id,
            agent_id=query.agent_id,
            entities=query.entities or None,
            sources=query.sources or None,
            created_after=query.created_after,
            created_before=query.created_before,
            include_expired=query.include_expired,
            ids=fts_ids,
            max_sensitivity=query.max_sensitivity,
            verification_states=query.verification_states or None,
            limit=2000 if fts_ids else 500,
        )
        # \w in a Unicode regex already matches Devanagari (and any other
        # script) code points, not just ASCII - [a-z0-9_]+ silently
        # tokenized ONLY Latin/ASCII text. A Hindi-only query produced an
        # EMPTY query_tokens set, which made `keyword` fall through to
        # its 0.4 default below regardless of actual content - the
        # line-69 filter (`keyword == 0`) then never excluded anything,
        # so an unrelated memory (e.g. old "Solar System" research
        # facts) could surface for ANY Hindi sentence with zero real
        # overlap. \w works for Hindi/Hinglish/mixed-script text alike.
        query_tokens = self._tokenize(query.text)
        query_embedding = await self.embeddings.embed(query.text) if query.text else None
        # ONE relationship query for the whole candidate set, not one per
        # candidate: N+1 lookups do not survive a decade of memories.
        counts = await self.store.relationship_counts([memory.id for memory in candidates])
        # CORPUS-FREQUENCY DOWNWEIGHT (a lightweight IDF). Static
        # stopwords ("and", "the") catch grammar, but a single-user,
        # single-agent store also accumulates its OWN ubiquitous tokens
        # - "vyom" and the user's own name appear in a large fraction of
        # every stored memory here, since nearly everything is either
        # about VYOM or belongs to one person. A query sharing ONLY
        # those universal tokens with an otherwise-unrelated memory
        # ("Can VYOM save Gunjan's details?" vs. an old "sent email to
        # gunjan@..." memory) scored keyword=0.22, close enough to a
        # genuine partial match (~0.25) that a static threshold alone
        # could not tell them apart - a real production bug. Tokens
        # appearing in more than a quarter of this search's own
        # candidate set are excluded from the overlap count entirely;
        # this adapts to whatever corpus VYOM actually has instead of
        # hardcoding any name.
        haystacks = {
            memory.id: " ".join(
                [memory.title, memory.summary, memory.content, *memory.tags, *memory.entities]
            ).lower()
            for memory in candidates
        }
        memory_token_sets = {mem_id: self._tokenize(text) for mem_id, text in haystacks.items()}
        document_frequency: dict[str, int] = {}
        for tokens in memory_token_sets.values():
            for token in tokens:
                document_frequency[token] = document_frequency.get(token, 0) + 1
        corpus_size = max(len(memory_token_sets), 1)
        overly_common_tokens = (
            {
                token for token, freq in document_frequency.items()
                if freq / corpus_size > 0.25
            }
            # Below this size, "appears in >25% of candidates" is
            # dominated by tiny-sample noise (with 3 memories, ANY
            # token shared by just 1 of them already exceeds 25%) - the
            # downweight only kicks in once there's enough of a corpus
            # for document frequency to mean something.
            if corpus_size >= 8 else set()
        )
        query_signal_tokens = query_tokens - overly_common_tokens
        ranked: list[MemorySearchResult] = []
        for memory in candidates:
            if (
                memory.verification_state == VerificationState.SUPERSEDED
                and not query.include_superseded
            ):
                continue
            haystack = haystacks[memory.id]
            memory_tokens = memory_token_sets[memory.id]
            # A query with real tokens but zero overlap is genuinely
            # unrelated (keyword=0), not an ambiguous "no query text"
            # case (which is the ONLY situation the 0.4 default below is
            # for - an empty query.text, not an empty token set from a
            # non-Latin query). Overlap is measured on SIGNAL tokens
            # only (query_signal_tokens) so shared corpus-ubiquitous
            # words never count as a match, but the RATIO denominator
            # still uses the full query_tokens count so a query made up
            # ENTIRELY of common words (rare in practice) does not
            # divide by zero or get an inflated ratio from a tiny
            # denominator.
            keyword = (
                len(query_signal_tokens & memory_tokens) / max(len(query_tokens), 1)
                if query.text else 0.4
            )
            semantic = 0.0
            if query_embedding is not None:
                embed_memory = getattr(self.embeddings, "embed_memory", None)
                memory_embedding = (
                    await embed_memory(memory, haystack) if embed_memory
                    else await self.embeddings.embed(haystack)
                )
                semantic = cosine_similarity(query_embedding, memory_embedding)
            relation_score = min(1.0, counts.get(memory.id, 0) / 4)
            score, reasons = relevance_score(
                memory,
                keyword_score=keyword,
                semantic_score=semantic,
                relationship_score=relation_score,
            )
            if query.text and keyword == 0 and semantic < 0.22:
                # Threshold raised from 0.05 to 0.22 (originally 0.2,
                # tightened further after finding a real-corpus case
                # that scored 0.204: "gunjan"/"vyom" recurring across an
                # email-send memory's title+summary+content produced
                # enough hash-embedding mass to just clear 0.2 even with
                # the corpus-frequency keyword downweight above already
                # correctly rejecting it on keyword grounds).
                # LocalHashEmbeddingProvider is a bag-of-hashed-tokens
                # cosine similarity, not real semantic embeddings -
                # genuinely related short phrases ("what is my business
                # name" vs "my business is Luxora Designs") score
                # 0.38-0.45; unrelated phrases sharing only ubiquitous
                # corpus tokens land in the 0.17-0.21 band purely from
                # repetition/hash noise, which is why 0.05 (and even
                # 0.2) let completely unrelated old memories surface for
                # an unrelated query - a real production bug. 0.22 sits
                # below every genuine match observed and above the
                # highest noise value found in this corpus.
                continue
            ranked.append(MemorySearchResult(memory=memory, score=score, reasons=reasons))
        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked[: query.limit]
