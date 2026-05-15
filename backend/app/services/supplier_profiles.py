from __future__ import annotations

from dataclasses import dataclass, field

PARSER_FAMILY_DIAGEO_ERP = "diageo_erp_statement"
PARSER_FAMILY_TRADE_STATEMENT = "trade_statement"
PARSER_FAMILY_STATEMENT_OF_ACCOUNT = "statement_of_account"
PARSER_FAMILY_GENERIC_STATEMENT = "generic_statement"

TRANSACTION_PUB_ALIASES: dict[str, set[str]] = {
    "careys": {"careys", "careyspub", "careysbar", "careystavern", "car18"},
    "canal": {"canal", "canalturn", "thecanalturn", "can02"},
    "corrcross": {"corrcross"},
}
DOCUMENT_METADATA_PUB_ALIASES: dict[str, set[str]] = {
    "careys": {"careyspub", "careystavern", "car18", "mardyke", "athlone", "n37ap95"},
    "canal": {"canalturn", "thecanalturn", "can02"},
    "corrcross": {"corrcross"},
}
DOCUMENT_RECIPIENT_PUB_ALIASES: dict[str, set[str]] = {
    "careys": {"careyspub", "careystavern", "car18"},
    "canal": {"canalturn", "thecanalturn", "can02"},
    "corrcross": {"corrcross"},
}
DOCUMENT_STATEMENT_PUB_ALIASES: dict[str, set[str]] = {
    "careys": {"careyspub", "careystavern", "car18", "carey01", "mardyke", "athlone", "n37ap95"},
    "canal": {"canalturn", "thecanalturn", "can02", "cana01", "ballymahon", "n39wr64"},
    "corrcross": {"corrcross"},
}


@dataclass(frozen=True, slots=True)
class SupplierProfile:
    canonical_name: str
    aliases: tuple[str, ...] = ()
    bank_aliases: tuple[str, ...] = ()
    parser_family: str | None = None
    pub_hints: dict[str, tuple[str, ...]] = field(default_factory=dict)


SUPPLIER_PROFILES: tuple[SupplierProfile, ...] = (
    SupplierProfile(
        canonical_name="Automatic Amusements",
        aliases=("automatic amusements", "moodmaster", "national autom"),
        bank_aliases=("moodmaster", "national autom", "nationalautom"),
        pub_hints={
            "careys": ("car18", "careys tavern", "careys pub"),
            "canal": ("can02", "canal turn"),
        },
    ),
    SupplierProfile(canonical_name="BOC", aliases=("boc", "ebilling", "boconline")),
    SupplierProfile(canonical_name="Booker", aliases=("booker",)),
    SupplierProfile(
        canonical_name="Bulmers",
        aliases=("bulmers", "bulmers ireland", "candcgroup", "c&c group"),
        bank_aliases=("bulmers irel", "bulmers ireland"),
        parser_family=PARSER_FAMILY_STATEMENT_OF_ACCOUNT,
    ),
    SupplierProfile(canonical_name="C&C Gleeson", aliases=("c&c gleeson", "c and c gleeson")),
    SupplierProfile(
        canonical_name="Connacht Bottlers",
        aliases=("connacht bottlers", "jj mahon and sons", "jj mahon", "jjmahons"),
        bank_aliases=("connacht bottl", "connacht bottlers"),
        parser_family=PARSER_FAMILY_TRADE_STATEMENT,
        pub_hints={
            "careys": ("carey01",),
            "canal": ("cana01",),
        },
    ),
    SupplierProfile(canonical_name="Caterers Cash & Carry", aliases=("caterers cash & carry", "seery", "seerys")),
    SupplierProfile(canonical_name="Chris Lynch Skip Hire & Waste Management Services", aliases=("chris lynch",)),
    SupplierProfile(canonical_name="Costco", aliases=("costco",)),
    SupplierProfile(
        canonical_name="Diageo",
        aliases=("diageo",),
        bank_aliases=("diageo ireland", "diageo"),
        parser_family=PARSER_FAMILY_DIAGEO_ERP,
    ),
    SupplierProfile(canonical_name="Little Luxuries", aliases=("little luxuries",)),
    SupplierProfile(canonical_name="Makro", aliases=("makro",)),
    SupplierProfile(
        canonical_name="M&J Gleeson",
        aliases=("m&j gleeson", "m and j gleeson"),
        bank_aliases=("m and j gleeso", "m&j gleeson"),
    ),
    SupplierProfile(canonical_name="Railway Corporation", aliases=("railway corporation",)),
    SupplierProfile(canonical_name="TCC", aliases=("tcc",)),
    SupplierProfile(canonical_name="Travis Perkins", aliases=("travis perkins", "travisperkins")),
    SupplierProfile(
        canonical_name="Heineken",
        aliases=("heineken", "heineken ireland"),
        bank_aliases=("heineken irela", "heineken ireland"),
        parser_family=PARSER_FAMILY_STATEMENT_OF_ACCOUNT,
    ),
)


def compact_profile_key(value: str | None) -> str:
    if not value:
        return ""
    return "".join(ch for ch in value.lower() if ch.isalnum())


_PROFILE_BY_KEY: dict[str, SupplierProfile] = {}
for profile in SUPPLIER_PROFILES:
    keys = {profile.canonical_name, *profile.aliases, *profile.bank_aliases}
    for key in keys:
        compacted = compact_profile_key(key)
        if compacted:
            _PROFILE_BY_KEY[compacted] = profile


def _profile_keys(profile: SupplierProfile) -> set[str]:
    return {
        compact_profile_key(profile.canonical_name),
        *(compact_profile_key(alias) for alias in profile.aliases),
        *(compact_profile_key(alias) for alias in profile.bank_aliases),
    }


def get_supplier_profile(candidate: str | None) -> SupplierProfile | None:
    compacted = compact_profile_key(candidate)
    if not compacted:
        return None
    return _PROFILE_BY_KEY.get(compacted)


def match_supplier_profile(candidate: str | None) -> SupplierProfile | None:
    compacted = compact_profile_key(candidate)
    if not compacted:
        return None

    exact_match = _PROFILE_BY_KEY.get(compacted)
    if exact_match is not None:
        return exact_match

    matched_profiles = {
        profile.canonical_name: profile
        for key, profile in _PROFILE_BY_KEY.items()
        if min(len(compacted), len(key)) >= 8
        and (key.startswith(compacted) or compacted.startswith(key))
    }.values()
    matched_profiles = list(matched_profiles)
    if len(matched_profiles) == 1:
        return matched_profiles[0]
    return None


def canonicalize_supplier_name(candidate: str | None) -> str | None:
    profile = match_supplier_profile(candidate)
    if profile is not None:
        return profile.canonical_name
    cleaned = (candidate or "").strip(" -,:;")
    return cleaned or None


def match_known_supplier_in_text(haystack: str) -> str | None:
    lowered = (haystack or "").lower()
    for profile in SUPPLIER_PROFILES:
        needles = (profile.canonical_name, *profile.aliases, *profile.bank_aliases)
        for needle in needles:
            if needle.lower() in lowered:
                return profile.canonical_name
    return None


def build_supplier_lookup_keys(candidate: str | None) -> set[str]:
    compacted = compact_profile_key(candidate)
    if not compacted:
        return set()

    profile = match_supplier_profile(candidate)
    if profile is None:
        return {compacted}

    return {key for key in _profile_keys(profile) if key}


def detect_statement_parser_family(*, supplier: str | None, text: str) -> str | None:
    profile = match_supplier_profile(supplier)
    if profile is not None and profile.parser_family:
        return profile.parser_family

    lowered = (text or "").lower()
    if "statement of account" in lowered and "customer account no" in lowered:
        return PARSER_FAMILY_STATEMENT_OF_ACCOUNT
    if "connacht bottlers" in lowered:
        return PARSER_FAMILY_TRADE_STATEMENT
    if any(token in lowered for token in ("sub account statement", "total sett disc", "this is not a financial document")):
        return PARSER_FAMILY_DIAGEO_ERP
    if "statement" in lowered:
        return PARSER_FAMILY_GENERIC_STATEMENT
    return None
