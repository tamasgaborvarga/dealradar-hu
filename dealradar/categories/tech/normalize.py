"""TECH normalization and validation rules."""

from __future__ import annotations

import re

from dealradar.categories.base import add_identifier, brand_from, scope_identifiers, search_text
from dealradar.categories.tech.attributes import (
    SsdInterface,
    TechKind,
    TechListingAttrs,
    TechProductAttrs,
    TechVariantAttrs,
)
from dealradar.core.enums import IdType, ListingKind
from dealradar.core.hu_parse import ParseError, parse_hu_number
from dealradar.core.identifiers import text_key
from dealradar.normalize.types import Issue, NormalizedListing, Severity, issue

SCOPED_IDS = frozenset({IdType.MPN})

_KIND_PATTERNS: tuple[tuple[TechKind, re.Pattern[str]], ...] = (
    (TechKind.LAPTOP, re.compile(r"\b(laptop|notebook|ultrabook)\b", re.I)),
    (TechKind.MONITOR, re.compile(r"\bmonitor\b", re.I)),
    (TechKind.GPU, re.compile(
        r"\b(videokártya|graphics card|geforce|radeon rx)\b"
        r"|\b(rtx|gtx)\s?\d{3,4}|\brx\s?\d{4}\b|\barc\s?[ab]\d{3}\b",
        re.I,
    )),
    (TechKind.SSD, re.compile(r"\bssd\b|\bnvme\b", re.I)),
    (TechKind.RAM, re.compile(r"\b(memória|memory|ram|dimm|so-dimm|sodimm)\b", re.I)),
    (TechKind.CPU, re.compile(
        r"\b(processzor|processor|cpu)\b|\bryzen [3579] \d{4}|\bcore (i[3579]|ultra)\b", re.I
    )),
)  # fmt: skip
_KIND_ATTR = {
    "processzor": TechKind.CPU, "cpu": TechKind.CPU, "videokártya": TechKind.GPU,
    "gpu": TechKind.GPU, "memória": TechKind.RAM, "ram": TechKind.RAM, "ssd": TechKind.SSD,
    "laptop": TechKind.LAPTOP, "notebook": TechKind.LAPTOP, "monitor": TechKind.MONITOR,
}  # fmt: skip

_SOCKET = re.compile(r"\b(AM[2-5]\+?|LGA\s?-?\d{3,4}|FM2\+?|sTRX4|SP[35]|TR5)\b", re.I)
_GPU = re.compile(
    r"\b(?P<fam>RTX|GTX)\s?(?P<num>\d{3,4})(?:\s?(?P<suf>Ti\s?SUPER|Ti|SUPER))?\b"
    r"|\b(?P<amd>RX)\s?(?P<anum>\d{3,4})(?:\s?(?P<asuf>XTX|XT|GRE))?\b"
    r"|\bArc\s?(?P<arc>[AB]\d{3})\b",
    re.I,
)
_RAM_TYPE = re.compile(r"(?<![A-Za-z])((?:LP)?DDR[2-5]X?)\b", re.I)
_CAPACITY = re.compile(r"(\d+(?:[.,]\d+)?)\s?(TB|GB)\b", re.I)
_KIT = re.compile(r"(\d{1,2})\s?[x\u00d7]\s?(\d{1,3})\s?GB\b", re.I)
_LAPTOP_RAM = re.compile(r"(\d{1,3})\s?GB\s?(?:(?:LP)?DDR\d\w?\s?)?(?:RAM|memória)\b", re.I)
_LAPTOP_STORAGE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s?(TB|GB)\s?(?:PCIe\s?)?(?:SSD|NVMe|HDD|eMMC|tárhely)\b", re.I
)
_SPEED = re.compile(r"(\d{4,5})\s?(MHz|MT/s)\b", re.I)
_PCIE_GEN = re.compile(r"pcie?\s?(?:gen\s?)?([345])(?:\.0)?\b|gen\s?([345])\b", re.I)
_M2 = re.compile(r"\bM\.2(?:\s?(2230|2242|2260|2280|22110))?\b", re.I)
_SCREEN = re.compile(r"(\d{2}(?:[.,]\d)?)\s?(?:\"|”|''|col+|inch|hüvelyk)", re.I)
_REFRESH = re.compile(r"(\d{2,3})\s?Hz\b", re.I)
_RES = re.compile(r"\b(\d{3,4})\s?[x\u00d7]\s?(\d{3,4})\b")
_RES_NAMES = {
    "4k": "3840x2160", "uhd": "3840x2160", "wqhd": "2560x1440", "qhd": "2560x1440",
    "fhd": "1920x1080", "full hd": "1920x1080", "1440p": "2560x1440", "1080p": "1920x1080",
}  # fmt: skip
_PANEL = re.compile(r"\b(QD-OLED|OLED|IPS|VA|TN|Mini[- ]?LED)\b", re.I)
_SEALED = re.compile(r"bontatlan|\bsealed\b|fóliás", re.I)
_INVOICE = re.compile(r"számlával|számla van|áfás számla|invoice", re.I)


def _gb(amount: str, unit: str) -> int:
    value = parse_hu_number(amount) * (
        1000 if unit.upper() == "TB" else 1
    )  # storage: 1 TB = 1000 GB
    if value != value.to_integral_value():
        raise ParseError(f"fractional GB: {amount}{unit}")
    return int(value)


def detect_kind(listing: NormalizedListing) -> TechKind | None:
    hint = listing.attr("típus", "kategória", "category", "type")
    if hint and (kind := _KIND_ATTR.get(hint.casefold().strip())):
        return kind
    for kind, pattern in _KIND_PATTERNS:
        if pattern.search(listing.title):
            return kind
    return None


def gpu_chipset(text: str) -> str | None:
    m = _GPU.search(text)
    if not m:
        return None
    if m["fam"]:
        suffix = re.sub(r"\s+", " ", m["suf"] or "").upper().replace("TI", "Ti")
        return f"{m['fam'].upper()} {m['num']}{(' ' + suffix) if suffix else ''}"
    if m["amd"]:
        return f"RX {m['anum']}{(' ' + m['asuf'].upper()) if m['asuf'] else ''}"
    return f"ARC {m['arc'].upper()}"


def socket(text: str) -> str | None:
    m = _SOCKET.search(text)
    return re.sub(r"[\s-]", "", m.group(1)).upper() if m else None


def ram_type(text: str) -> str | None:
    types = {t.upper() for t in _RAM_TYPE.findall(text)}
    return types.pop() if len(types) == 1 else None


def ssd_interface(text: str) -> SsdInterface | None:
    if re.search(r"\bnvme\b", text, re.I):
        m = _PCIE_GEN.search(text)
        gen = (m.group(1) or m.group(2)) if m else None
        return SsdInterface(f"NVME_PCIE{gen}") if gen else SsdInterface.NVME
    if re.search(r"\bsata\b", text, re.I):
        return SsdInterface.SATA
    return None


def resolution(text: str) -> str | None:
    m = _RES.search(text)
    if m:
        return f"{m.group(1)}x{m.group(2)}"
    lowered = text.casefold()
    for name, value in _RES_NAMES.items():
        if re.search(rf"\b{name}\b", lowered):
            return value
    return None


def normalize(listing: NormalizedListing) -> NormalizedListing:
    issues: list[Issue] = []
    updates = brand_from(listing, "gyártó", "márka", "manufacturer", "brand")
    brand_key = updates.get("brand_key", listing.brand_key)
    model = listing.model or listing.attr("modell", "model", "típusszám", "termék")
    if model and not listing.model:
        updates |= {"model": model, "model_key": text_key(model)}

    ids, id_issues = add_identifier(
        listing, IdType.GTIN, listing.attr("ean", "ean kód", "vonalkód", "gtin")
    )
    listing = listing.model_copy(update={"identifiers": ids})
    ids, mpn_issues = add_identifier(
        listing,
        IdType.MPN,
        listing.attr("gyártói cikkszám", "cikkszám", "mpn", "part number", "p/n"),
    )
    issues += id_issues + mpn_issues

    text = search_text(listing)
    kind = detect_kind(listing)
    product: dict[str, object] = {"kind": kind}
    variant: dict[str, object] = {}

    # values from the title vs. the spec table must agree
    for field, extract in (
        ("cpu_socket", socket),
        ("ram_type", ram_type),
        ("gpu_chipset", gpu_chipset),
    ):
        from_title = extract(listing.title)
        from_specs = extract(" ".join(listing.attributes.values()))
        if from_title and from_specs and from_title != from_specs:
            issues.append(
                issue(f"conflicting_{field}", field, f"title {from_title} vs specs {from_specs}")
            )
            continue
        value = from_title or from_specs
        if field == "gpu_chipset" and kind is TechKind.LAPTOP:
            product["gpu_model"] = value
        elif field == "ram_type" and kind not in (TechKind.RAM, TechKind.LAPTOP, None):
            continue  # e.g. "supports DDR5" on a CPU page is not the item's own RAM type
        elif field == "cpu_socket" and kind not in (TechKind.CPU, None):
            continue
        elif field != "gpu_chipset" or kind in (TechKind.GPU, None):
            product[field] = value

    try:
        if kind is TechKind.SSD:
            caps = {_gb(a, u) for a, u in _CAPACITY.findall(listing.title)}
            if len(caps) == 1:
                variant["capacity_gb"] = caps.pop()
            elif caps:
                issues.append(
                    issue("capacity_ambiguous", "capacity", f"several capacities {sorted(caps)}")
                )
            product["ssd_interface"] = ssd_interface(text)
            m2 = _M2.search(text)
            if m2:
                product["ssd_form_factor"] = f"M.2 {m2.group(1)}" if m2.group(1) else "M.2"
            elif re.search(r"2[.,]5\s?(\"|”|col|inch)", text, re.I):
                product["ssd_form_factor"] = "2.5IN"
        elif kind is TechKind.RAM:
            kit = _KIT.search(listing.title)
            caps = {_gb(a, u) for a, u in _CAPACITY.findall(_KIT.sub("", listing.title))}
            if kit:
                n, each = int(kit.group(1)), int(kit.group(2))
                variant |= {"modules": n, "capacity_gb": n * each}
                if caps and caps != {n * each}:
                    issues.append(
                        issue(
                            "capacity_conflict", "capacity", f"kit {n}x{each}GB vs {sorted(caps)}"
                        )
                    )
            elif len(caps) == 1:
                variant |= {
                    "capacity_gb": caps.pop(),
                    "modules": 1 if "1x" in listing.title.lower() else None,
                }
            speed = _SPEED.search(text)
            if speed:
                variant["speed_mts"] = int(speed.group(1))
        elif kind is TechKind.GPU:
            caps = {_gb(a, u) for a, u in _CAPACITY.findall(listing.title) if u.upper() == "GB"}
            if len(caps) == 1:
                variant["memory_gb"] = caps.pop()
        elif kind is TechKind.LAPTOP:
            ram = _LAPTOP_RAM.search(text)
            storage = _LAPTOP_STORAGE.search(text)
            if ram:
                variant["memory_gb"] = int(ram.group(1))
            if storage:
                variant["storage_gb"] = _gb(storage.group(1), storage.group(2))
            cpu = re.search(
                r"\b(Ryzen\s?[3579]\s?\w+|Core\s?(?:i[3579]|Ultra\s?[579])[\s-]?\w+|Apple M\d\w*)",
                text,
                re.I,
            )
            if cpu:
                product["cpu_model"] = re.sub(r"\s+", " ", cpu.group(1))
        elif kind is TechKind.MONITOR:
            screen = _SCREEN.search(text)
            if screen:
                product["screen_diag_tenth_in"] = int(parse_hu_number(screen.group(1)) * 10)
            hz = _REFRESH.search(text)
            if hz:
                product["refresh_hz"] = int(hz.group(1))
            product["resolution"] = resolution(text)
            panel = _PANEL.search(text)
            if panel:
                product["panel"] = panel.group(1).upper().replace(" ", "-")
    except ParseError as exc:
        issues.append(issue("spec_unparsable", "specs", str(exc)))

    variant_attrs = TechVariantAttrs.model_validate(
        {k: v for k, v in variant.items() if v is not None}
    )
    listing = listing.model_copy(
        update={
            **updates,
            "identifiers": scope_identifiers(listing.identifiers, brand_key, SCOPED_IDS),
            "product_attrs": TechProductAttrs.model_validate(
                {k: v for k, v in product.items() if v is not None}
            ),
            "variant_attrs": variant_attrs,
            "listing_attrs": TechListingAttrs(
                sealed=True
                if _SEALED.search(listing.title + " " + (listing.description or ""))
                else None,
                invoice_available=True if _INVOICE.search(listing.description or "") else None,
            ),
            "variant_key": variant_key(kind, variant_attrs),
        }
    )
    return listing.with_issues(*issues)


def variant_key(kind: TechKind | None, v: TechVariantAttrs) -> str | None:
    if kind is TechKind.SSD:
        return f"{v.capacity_gb}GB" if v.capacity_gb else None
    if kind is TechKind.RAM:
        if not v.capacity_gb:
            return None
        if v.modules and v.modules > 1:
            return f"{v.capacity_gb}GB-{v.modules}X{v.capacity_gb // v.modules}GB"
        return f"{v.capacity_gb}GB"
    if kind is TechKind.GPU:
        return f"{v.memory_gb}GB" if v.memory_gb else "default"
    if kind is TechKind.LAPTOP:
        return f"{v.memory_gb}GB-{v.storage_gb}GB" if v.memory_gb and v.storage_gb else None
    return "default"


def validate(listing: NormalizedListing) -> list[Issue]:
    p = listing.product_attrs
    v = listing.variant_attrs
    assert isinstance(p, TechProductAttrs) and isinstance(v, TechVariantAttrs)
    out: list[Issue] = []
    warn = Severity.WARNING
    if p.kind is None:
        out.append(issue("kind_unknown", "kind", "product type not recognized", warn))
    if not listing.brand:
        out.append(issue("manufacturer_missing", "manufacturer", "manufacturer unknown"))
    if not listing.identifiers and not listing.model:
        out.append(issue("no_identity", "identity", "no EAN, MPN or model name", warn))
    if p.kind is TechKind.SSD:
        if not v.capacity_gb:
            out.append(issue("capacity_missing", "capacity", "SSD capacity unknown"))
        if p.ssd_interface is None:
            out.append(issue("interface_missing", "ssd_interface", "SSD interface unknown", warn))
    elif p.kind is TechKind.RAM:
        if p.ram_type is None:
            out.append(issue("ram_type_missing", "ram_type", "RAM type (DDR4/DDR5) unknown"))
        if not v.capacity_gb:
            out.append(issue("capacity_missing", "capacity", "RAM capacity unknown"))
    elif p.kind is TechKind.GPU:
        if p.gpu_chipset is None:
            out.append(issue("gpu_chipset_missing", "gpu_chipset", "GPU chipset unknown"))
        if not v.memory_gb:
            out.append(issue("vram_missing", "memory_gb", "VRAM size unknown", warn))
    elif p.kind is TechKind.CPU:
        if p.cpu_socket is None:
            out.append(issue("socket_missing", "cpu_socket", "CPU socket unknown", warn))
    elif p.kind is TechKind.LAPTOP:
        if listing.variant_key is None:
            out.append(
                issue("config_missing", "configuration", "RAM/storage configuration unknown")
            )
    elif p.kind is TechKind.MONITOR and (p.screen_diag_tenth_in is None or p.resolution is None):
        out.append(
            issue("monitor_specs_missing", "specs", "screen size or resolution unknown", warn)
        )
    if listing.listing_kind is not ListingKind.RETAIL and listing.condition is None:
        out.append(issue("condition_missing", "condition", "second-hand listing without condition"))
    return out
