"""Build a complete, versioned evidence snapshot for the local Jana reader.

The reader sees only published article text, never FAQ questions or test cases.
It may select sentence IDs; this module turns those IDs back into exact quotes.
No model-written factual text is accepted by the renderer.
"""

from dataclasses import dataclass
import hashlib
import json
import re
from types import MappingProxyType
from typing import Mapping, Sequence
from uuid import UUID

from app.services.jana_errors import JanaUnavailable

MAX_ARTICLES = 100
MAX_ARTICLE_CHARS = 20_000
MAX_TOTAL_CHARS = 48_000
MAX_PROMPT_CHARS = 64_000

# Keep semicolons, colons and comma-separated qualifications together. A dot
# inside .ics, a decimal or an abbreviation without following whitespace does
# not end a span. Paragraph breaks also bound unpunctuated text.
_BOUNDARY = re.compile(r'[.!?][\"»”’\)\]]*(?=\s|$)|\n[ \t]*\n')


@dataclass(frozen=True)
class EvidenceSpan:
    id: str
    article_id: str
    start: int
    end: int
    text: str
    ordinal: int


@dataclass(frozen=True)
class EvidenceDocument:
    id: str
    title: str
    source_title: str
    content: str
    sha256: str
    spans: tuple[EvidenceSpan, ...]


@dataclass(frozen=True)
class EvidenceBundle:
    documents: tuple[EvidenceDocument, ...]
    spans: tuple[EvidenceSpan, ...]
    by_id: Mapping[str, EvidenceSpan]
    by_article_id: Mapping[str, EvidenceDocument]
    prompt_text: str


def _required_text(article: dict, key: str) -> str:
    value = article.get(key)
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise JanaUnavailable(f"Knowledge article has invalid {key}")
    return value


def _sentence_offsets(content: str) -> list[tuple[int, int]]:
    """Preserve original offsets and every non-whitespace character."""
    result = []
    start = 0
    ends = [match.end() for match in _BOUNDARY.finditer(content)]
    if not ends or ends[-1] != len(content):
        ends.append(len(content))
    for end in ends:
        left, right = start, end
        while left < right and content[left].isspace():
            left += 1
        while right > left and content[right - 1].isspace():
            right -= 1
        if left < right:
            result.append((left, right))
        start = end
    return result


def prepare_evidence(
    articles: Sequence[dict], *, max_total_chars: int = MAX_TOTAL_CHARS,
    max_prompt_chars: int = MAX_PROMPT_CHARS,
) -> EvidenceBundle:
    """Validate and include the whole active knowledge base, or fail explicitly.

    The character budgets bound memory and prompt construction. The local model
    adapter must additionally check its actual tokenizer/context limit; this
    function never guesses a token count or truncates a source to make it fit.
    Article order does not affect IDs; any content edit invalidates all IDs for
    that article, including spans whose text itself did not change.
    """
    if len(articles) > MAX_ARTICLES:
        raise JanaUnavailable("Knowledge base exceeds the supported article limit")
    if max_total_chars <= 0 or max_prompt_chars <= 0:
        raise ValueError("Evidence budgets must be positive")
    documents = []
    seen = set()
    total_chars = 0
    for article in articles:
        if not isinstance(article, dict):
            raise JanaUnavailable("Knowledge article is not an object")
        # The database query already filters active=True. Explicitly inactive
        # rows are also excluded when this module is used by local evaluation.
        if article.get("active") is False:
            continue
        if "active" in article and article["active"] is not True:
            raise JanaUnavailable("Knowledge article has invalid publication state")
        try:
            article_id = str(UUID(str(article["id"])))
        except (KeyError, ValueError, AttributeError) as exc:
            raise JanaUnavailable("Knowledge article has invalid ID") from exc
        if article_id in seen:
            raise JanaUnavailable("Knowledge base has duplicate article IDs")
        seen.add(article_id)
        title = _required_text(article, "title")
        source_title = _required_text(article, "source_title")
        content = _required_text(article, "content")
        if len(title) > 500 or len(source_title) > 500:
            raise JanaUnavailable("Knowledge article title exceeds the supported limit")
        if len(content) > MAX_ARTICLE_CHARS:
            raise JanaUnavailable("Knowledge article exceeds the supported text limit")
        total_chars += len(title) + len(source_title) + len(content)
        if total_chars > max_total_chars:
            raise JanaUnavailable("Whole knowledge base exceeds the evidence budget")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        spans = []
        for ordinal, (start, end) in enumerate(_sentence_offsets(content)):
            identity = f"{article_id}\0{digest}\0{start}\0{end}"
            span_id = "S" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
            spans.append(EvidenceSpan(span_id, article_id, start, end,
                                      content[start:end], ordinal))
        documents.append(EvidenceDocument(article_id, title, source_title,
                                          content, digest, tuple(spans)))
    documents.sort(key=lambda item: item.id)
    all_spans = tuple(span for doc in documents for span in doc.spans)
    by_id = {span.id: span for span in all_spans}
    if len(by_id) != len(all_spans):
        raise JanaUnavailable("Knowledge evidence ID collision")
    # Ordered sentences preserve the full context for negation, exceptions and
    # pronouns; each source remains visibly grouped. No external URL, stored
    # example question, keyword list or private profile reaches the reader.
    prompt_text = json.dumps({"articles": [
        {"article_id": doc.id, "title": doc.title, "source_title": doc.source_title,
         "sentences": [{"id": span.id, "text": span.text} for span in doc.spans]}
        for doc in documents
    ]}, ensure_ascii=False, separators=(",", ":"))
    if len(prompt_text) > max_prompt_chars:
        raise JanaUnavailable("Whole knowledge base exceeds the model prompt budget")
    return EvidenceBundle(tuple(documents), all_spans, MappingProxyType(by_id),
                          MappingProxyType({doc.id: doc for doc in documents}), prompt_text)


def select_excerpts(
    bundle: EvidenceBundle, span_ids: Sequence[str], *, max_spans: int = 8,
    max_chars: int = 2400,
) -> list[dict]:
    """Resolve a bounded selection to exact quotes, at most one per article.

    Separated selections from one article include their intervening context.
    This preserves a verbatim substring and gives the UI unique source IDs.
    Malformed, stale, unknown or over-budget selections fail rather than being
    silently shortened or partially trusted.
    """
    if isinstance(span_ids, (str, bytes)) or not span_ids or len(span_ids) > max_spans:
        raise ValueError("Invalid number of evidence selections")
    if any(not isinstance(span_id, str) for span_id in span_ids):
        raise ValueError("Evidence IDs must be strings")
    if len(set(span_ids)) != len(span_ids):
        raise ValueError("Duplicate evidence selections")
    groups: dict[str, list[EvidenceSpan]] = {}
    for span_id in span_ids:
        try:
            span = bundle.by_id[span_id]
        except KeyError as exc:
            raise ValueError("Unknown or stale evidence ID") from exc
        groups.setdefault(span.article_id, []).append(span)
    sources = []
    total_chars = 0
    for article_id, spans in groups.items():
        document = bundle.by_article_id[article_id]
        start = min(span.start for span in spans)
        end = max(span.end for span in spans)
        excerpt = document.content[start:end]
        total_chars += len(excerpt)
        if total_chars > max_chars:
            raise ValueError("Selected evidence exceeds the answer length budget")
        sources.append({"id": article_id, "title": document.source_title,
                        "url": f"/api/v1/ai/sources/{article_id}", "excerpt": excerpt})
    return sources
