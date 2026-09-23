"""Kenya's 47 counties plus common towns/estates that job ads use instead of a county."""
from __future__ import annotations

import re
import unicodedata

COUNTIES = [
    (1, "Mombasa"), (2, "Kwale"), (3, "Kilifi"), (4, "Tana River"), (5, "Lamu"),
    (6, "Taita-Taveta"), (7, "Garissa"), (8, "Wajir"), (9, "Mandera"), (10, "Marsabit"),
    (11, "Isiolo"), (12, "Meru"), (13, "Tharaka-Nithi"), (14, "Embu"), (15, "Kitui"),
    (16, "Machakos"), (17, "Makueni"), (18, "Nyandarua"), (19, "Nyeri"), (20, "Kirinyaga"),
    (21, "Murang'a"), (22, "Kiambu"), (23, "Turkana"), (24, "West Pokot"), (25, "Samburu"),
    (26, "Trans Nzoia"), (27, "Uasin Gishu"), (28, "Elgeyo-Marakwet"), (29, "Nandi"),
    (30, "Baringo"), (31, "Laikipia"), (32, "Nakuru"), (33, "Narok"), (34, "Kajiado"),
    (35, "Kericho"), (36, "Bomet"), (37, "Kakamega"), (38, "Vihiga"), (39, "Bungoma"),
    (40, "Busia"), (41, "Siaya"), (42, "Kisumu"), (43, "Homa Bay"), (44, "Migori"),
    (45, "Kisii"), (46, "Nyamira"), (47, "Nairobi"),
]

# Town / estate / area -> county name (must exactly match a name in COUNTIES).
# Add to this as the dry-run profile shows unmapped locations.
TOWNS = {
    # Nairobi
    "westlands": "Nairobi", "kilimani": "Nairobi", "karen": "Nairobi", "lavington": "Nairobi",
    "kileleshwa": "Nairobi", "upper hill": "Nairobi", "upperhill": "Nairobi",
    "parklands": "Nairobi", "industrial area": "Nairobi", "embakasi": "Nairobi",
    "kasarani": "Nairobi", "langata": "Nairobi", "south b": "Nairobi", "south c": "Nairobi",
    "eastleigh": "Nairobi", "ruaraka": "Nairobi", "roysambu": "Nairobi", "gigiri": "Nairobi",
    "muthaiga": "Nairobi", "runda": "Nairobi", "ngara": "Nairobi", "dagoretti": "Nairobi",
    "kawangware": "Nairobi", "kibera": "Nairobi", "donholm": "Nairobi", "buruburu": "Nairobi",
    "umoja": "Nairobi", "kahawa": "Nairobi", "utawala": "Nairobi", "jkia": "Nairobi",
    "pangani": "Nairobi", "nairobi west": "Nairobi", "nairobi cbd": "Nairobi",
    # Kiambu
    "thika": "Kiambu", "ruiru": "Kiambu", "juja": "Kiambu", "kikuyu": "Kiambu",
    "limuru": "Kiambu", "githunguri": "Kiambu", "gatundu": "Kiambu", "tatu city": "Kiambu",
    "kabete": "Kiambu", "karuri": "Kiambu",
    # Kajiado
    "ngong": "Kajiado", "ongata rongai": "Kajiado", "rongai": "Kajiado",
    "kitengela": "Kajiado", "kiserian": "Kajiado", "isinya": "Kajiado",
    # Machakos
    "athi river": "Machakos", "mavoko": "Machakos", "syokimau": "Machakos",
    "mlolongo": "Machakos", "konza": "Machakos",
    # Rift Valley, Central, Western, Coast, North
    "naivasha": "Nakuru", "gilgil": "Nakuru", "molo": "Nakuru", "njoro": "Nakuru",
    "nanyuki": "Laikipia", "nyahururu": "Laikipia", "eldoret": "Uasin Gishu",
    "kitale": "Trans Nzoia", "kapsabet": "Nandi", "karatina": "Nyeri",
    "kerugoya": "Kirinyaga", "mwea": "Kirinyaga", "wote": "Makueni",
    "malindi": "Kilifi", "watamu": "Kilifi", "mtwapa": "Kilifi", "mariakani": "Kilifi",
    "diani": "Kwale", "ukunda": "Kwale", "voi": "Taita-Taveta",
    "nyali": "Mombasa", "bamburi": "Mombasa", "likoni": "Mombasa", "changamwe": "Mombasa",
    "lodwar": "Turkana", "kakuma": "Turkana", "lokichoggio": "Turkana",
    "dadaab": "Garissa", "isebania": "Migori", "awendo": "Migori", "mumias": "Kakamega",
    "webuye": "Bungoma", "kimilili": "Bungoma", "sotik": "Bomet", "kilgoris": "Narok",
    "maasai mara": "Narok", "kenol": "Murang'a", "maragua": "Murang'a",
}


def _norm_location(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = s.replace("'", "")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\b(county|city|town|sub)\b", " ", s)  # "Nairobi County", "Kisumu City"
    return re.sub(r"\s+", " ", s).strip()


_CODE_BY_NAME = {name: code for code, name in COUNTIES}
_LOOKUP: dict[str, tuple[int, str]] = {}
for _code, _name in COUNTIES:
    _LOOKUP[_norm_location(_name)] = (_code, _name)
for _town, _county in TOWNS.items():
    _LOOKUP[_norm_location(_town)] = (_CODE_BY_NAME[_county], _county)  # KeyError = typo

_REGEX = re.compile(
    r"\b(" + "|".join(re.escape(a) for a in sorted(_LOOKUP, key=len, reverse=True)) + r")\b"
)
_REMOTE = re.compile(r"\b(remote|work from home|wfh|telecommute)\b")


def map_location(text: str | None) -> dict:
    """Return {'county': str|None, 'county_code': int|None, 'is_remote': bool}.

    Segments are tried left to right, so "Westlands, Nairobi" resolves on "Westlands".
    """
    result = {"county": None, "county_code": None, "is_remote": False}
    if not text:
        return result
    result["is_remote"] = bool(_REMOTE.search(_norm_location(text)))
    for segment in re.split(r"[,;/|]| - ", text):
        m = _REGEX.search(_norm_location(segment))
        if m:
            code, name = _LOOKUP[m.group(1)]
            result.update(county=name, county_code=code)
            break
    return result


def is_location_only(text: str) -> bool:
    """True if the text is nothing but known places, e.g. 'Nairobi, Kenya'."""
    parts = [p for p in re.split(r"[,/|]", text) if p.strip()]
    return bool(parts) and all(
        _norm_location(p) in _LOOKUP or _norm_location(p) == "kenya" for p in parts
    )