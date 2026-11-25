"""Parsing and validating a pasted Claude answer. Invalid input is rejected with reasons."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from pydantic import ValidationError

from dealradar.claude_bridge.package import AnalysisPackage
from dealradar.claude_bridge.schema import AnalysisResponse, Recommendation
from dealradar.normalize.text import clean_text

MAX_RESPONSE_BYTES = 64 * 1024
_FENCED = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)
_URL = re.compile(r"https?://|www\.|\b[a-z0-9-]+\.(?:hu|com|net|org|io|eu)\b/?", re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE = re.compile(r"(?:\+36|06)[\s/-]?\d{1,2}[\s/-]?\d{3}[\s/-]?\d{3,4}")


@dataclass(frozen=True)
class ParseResult:
    accepted: bool
    response: AnalysisResponse | None
    errors: tuple[str, ...]


def _extract_json(text: str) -> object:
    """One JSON object: plain, inside a ```json fence, or between the first '{' and last '}'."""
    stripped = text.strip()
    candidates = [stripped]
    fenced = _FENCED.search(stripped)
    if fenced:
        candidates.insert(0, fenced.group(1))
    start, end = stripped.find("{"), stripped.rfind("}")
    if 0 <= start < end:
        candidates.append(stripped[start : end + 1])
    last_error = "no JSON object found"
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = f"invalid JSON: {exc.msg} (line {exc.lineno})"
    raise ValueError(last_error)


def _texts(r: AnalysisResponse) -> list[str]:
    return [
        r.summary,
        *(f.evidence for f in r.risk_flags),
        *r.questions_for_seller,
        *r.missing_information,
        *(d.reason for d in r.facts_disputed),
    ]


def parse_response(text: str, package: AnalysisPackage) -> ParseResult:
    def reject(*errors: str) -> ParseResult:
        return ParseResult(False, None, tuple(errors))

    if not text or not text.strip():
        return reject("empty answer")
    if len(text.encode("utf-8")) > MAX_RESPONSE_BYTES:
        return reject(f"answer larger than {MAX_RESPONSE_BYTES} bytes")
    try:
        data = _extract_json(text)
    except ValueError as exc:
        return reject(str(exc))
    if not isinstance(data, dict):
        return reject("the answer must be one JSON object")
    try:
        # JSON mode: strict types, enums accepted as their string values (no coercion of 1 -> "1").
        response = AnalysisResponse.model_validate_json(json.dumps(data))
    except ValidationError as exc:
        return reject(
            *(f"{'.'.join(str(p) for p in e['loc']) or '(root)'}: {e['msg']}" for e in exc.errors())
        )

    errors: list[str] = []
    if response.request_id != package.request_id:
        errors.append(
            f"request_id {response.request_id!r} belongs to another analysis "
            f"(expected {package.request_id!r})"
        )
    unknown = [d.key for d in response.facts_disputed if d.key not in package.fact_keys()]
    if unknown:
        errors.append(f"a vitatott tények ismeretlen azonosítókra hivatkoznak: {unknown}")
    if (
        response.recommendation is Recommendation.CONSIDER
        and response.confidence == "HIGH"
        and package.missing
    ):
        errors.append("ellentmondás: magas bizonyosságú „megfontolandó”, pedig adat hiányzik")
    for t in _texts(response):
        if _URL.search(t):
            errors.append(f"link nem megengedett: {t[:80]!r}")
        if _EMAIL.search(t):
            errors.append(f"e-mail-cím nem megengedett: {t[:80]!r}")
        if _PHONE.search(t):
            errors.append(f"telefonszám nem megengedett: {t[:80]!r}")
        if clean_text(t, len(t) + 1) != " ".join(t.split()):
            errors.append(f"rejtett vagy vezérlőkarakter a szövegben: {t[:80]!r}")
    if errors:
        return ParseResult(False, None, tuple(dict.fromkeys(errors)))
    return ParseResult(True, response, ())
