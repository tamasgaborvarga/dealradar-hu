"""Matching cascade (ARCHITECTURE.md §7): identifier -> category rule key -> fuzzy.

Only identifier hits and decisive rule keys without contradictions are AUTO_MATCH.
Fuzzy similarity and AI suggestions only ever produce REVIEW candidates.
"""

from __future__ import annotations

from collections.abc import Sequence
from difflib import SequenceMatcher

from dealradar.core.enums import IdType, MatchMethod
from dealradar.matching.types import (
    MatchingRules,
    MatchOutcome,
    OutcomeKind,
    ProductCandidate,
    ScoredCandidate,
)
from dealradar.normalize.types import NormalizedListing

_ID_METHOD = {
    IdType.GTIN: (MatchMethod.GTIN, 100),
    IdType.MPN: (MatchMethod.MPN, 95),
    IdType.STYLE_CODE: (MatchMethod.STYLE_CODE, 95),
}
_ID_TYPE = {method: id_type for id_type, (method, _) in _ID_METHOD.items()}
MAX_FUZZY_CANDIDATES = 5


def similarity(a: str, b: str) -> int:
    """Order-insensitive token similarity 0..100 (stdlib difflib, ADR-023)."""
    ta, tb = " ".join(sorted(a.split())), " ".join(sorted(b.split()))
    return round(SequenceMatcher(None, ta, tb).ratio() * 100)


def _brand_compatible(listing: NormalizedListing, product: ProductCandidate) -> bool:
    return listing.brand_key is not None and listing.brand_key == product.brand_key


def match(
    listing: NormalizedListing,
    candidates: Sequence[ProductCandidate],
    rules: MatchingRules,
) -> MatchOutcome:
    pool = [c for c in candidates if c.category is listing.category]

    # 1. identifiers -------------------------------------------------------------------------
    id_hits: dict[int, tuple[MatchMethod, int, int, str]] = {}
    for ident in listing.identifiers:
        if ident.id_type not in _ID_METHOD:
            continue
        for product in pool:
            variant_id = product.identifiers().get((ident.id_type, ident.value))
            if variant_id is None:
                continue
            if rules.identifier_requires_brand(ident.id_type) and not _brand_compatible(
                listing, product
            ):
                continue  # MPNs/style codes are only unique within one manufacturer
            method, conf = _ID_METHOD[ident.id_type]
            best = id_hits.get(product.product_id)
            if best is None or conf > best[1]:
                id_hits[product.product_id] = (
                    method,
                    conf,
                    variant_id,
                    f"{ident.id_type}={ident.raw}",
                )

    if len(id_hits) > 1:
        return MatchOutcome(
            kind=OutcomeKind.CONFLICT,
            reasons=("identifiers point to different products",),
            candidates=tuple(
                ScoredCandidate(pid, m, c, r) for pid, (m, c, _, r) in sorted(id_hits.items())
            ),
        )
    if len(id_hits) == 1:
        ((product_id, (method, conf, variant_id, reason)),) = id_hits.items()
        product = next(p for p in pool if p.product_id == product_id)
        problems = rules.contradictions(listing, product)
        if problems:
            return MatchOutcome(
                kind=OutcomeKind.CONFLICT,
                reasons=(reason, *problems),
                candidates=(ScoredCandidate(product_id, method, conf, reason),),
            )
        pinned = variant_id if rules.identifier_pins_variant(_ID_TYPE[method]) else None
        return _with_variant(listing, product, method, conf, (reason,), pinned)

    # 2. category rule key ---------------------------------------------------------------------
    key = rules.rule_key(listing)
    if key is not None:
        rule_hits = [p for p in pool if rules.product_rule_key(p) == key]
        clean = [p for p in rule_hits if not rules.contradictions(listing, p)]
        if len(clean) == 1 and len(rule_hits) == 1 and rules.rule_key_decisive:
            return _with_variant(listing, clean[0], MatchMethod.RULE, 90, (f"rule key {key}",))
        if clean:
            why = "not decisive for this category" if len(clean) == 1 else "several products"
            return MatchOutcome(
                kind=OutcomeKind.REVIEW,
                reasons=(f"rule key {key} ({why})",),
                candidates=tuple(
                    ScoredCandidate(p.product_id, MatchMethod.RULE, 80, f"rule key {key}")
                    for p in clean
                ),
            )
        if rule_hits:  # same name, contradicting specs: show it, a human must decide
            return MatchOutcome(
                kind=OutcomeKind.REVIEW,
                reasons=(f"rule key {key} matches but specs contradict",),
                candidates=tuple(
                    ScoredCandidate(
                        p.product_id,
                        MatchMethod.RULE,
                        40,
                        "; ".join(rules.contradictions(listing, p)),
                    )
                    for p in rule_hits
                ),
            )

    # 3. fuzzy title similarity (never automatic) ------------------------------------------------
    scored = []
    for product in pool:
        if listing.brand_key and product.brand_key and listing.brand_key != product.brand_key:
            continue
        if rules.contradictions(listing, product):
            continue
        score = similarity(listing.title_key, product.title_key)
        if score >= rules.fuzzy_threshold:
            scored.append(ScoredCandidate(product.product_id, MatchMethod.FUZZY, score, "title"))
    if scored:
        scored.sort(key=lambda c: (-c.confidence, c.product_id))
        return MatchOutcome(
            kind=OutcomeKind.REVIEW,
            reasons=("fuzzy title similarity only",),
            candidates=tuple(scored[:MAX_FUZZY_CANDIDATES]),
        )
    return MatchOutcome(kind=OutcomeKind.NO_MATCH)


def _with_variant(
    listing: NormalizedListing,
    product: ProductCandidate,
    method: MatchMethod,
    confidence: int,
    reasons: tuple[str, ...],
    identifier_variant_id: int | None = None,
) -> MatchOutcome:
    """Product is decided; resolve the variant from the listing's category variant key."""
    by_key = product.variant_by_key(listing.variant_key) if listing.variant_key else None
    if identifier_variant_id is not None:
        if by_key is not None and by_key.variant_id != identifier_variant_id:
            return MatchOutcome(
                kind=OutcomeKind.CONFLICT,
                product_id=product.product_id,
                reasons=(*reasons, f"identifier variant != listing variant {listing.variant_key}"),
                candidates=(ScoredCandidate(product.product_id, method, confidence, reasons[0]),),
            )
        variant_id: int | None = identifier_variant_id
    else:
        variant_id = by_key.variant_id if by_key else None
    extra = () if variant_id else (f"variant {listing.variant_key or '?'} not yet known",)
    return MatchOutcome(
        kind=OutcomeKind.AUTO_MATCH,
        product_id=product.product_id,
        variant_id=variant_id,
        method=method,
        confidence=confidence,
        reasons=(*reasons, *extra),
    )
