from __future__ import annotations

from dataclasses import dataclass

# ISO 3779 transliteration table for the VIN check digit (position 9).
# Each value is the "encoded" value used in the weighted sum; I, O and Q are
# never present in a VIN.
_VIN_TRANSLITERATION: dict[str, int] = {
    "0": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
    "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "H": 8,
    "J": 1, "K": 2, "L": 3, "M": 4, "N": 5, "P": 7, "R": 9,
    "S": 2, "T": 3, "U": 4, "V": 5, "W": 6, "X": 7, "Y": 8, "Z": 9,
}

# Weights per position for the check-digit computation.
_VIN_POSITION_WEIGHTS = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]

# Year code from VIN position 10 (ISO 3779, 30-year cycle). Letters for
# 1980..2000 (A..Y, skipping I/O/Q/Z), digits 1..9 for 2001..2009, then the
# same cycle repeats for 2010+.
_LETTER_CODES = "ABCDEFGHJKLMNPRSTUVWXY"  # A=1980 ... Y=2000 (21 entries)
_YEAR_CODES: dict[str, int] = {}
for _offset, _code in enumerate(_LETTER_CODES):
    _YEAR_CODES[_code] = 1980 + _offset
for _offset, _digit in enumerate("123456789", start=1):
    _YEAR_CODES[_digit] = 2000 + _offset
for _offset, _code in enumerate(_LETTER_CODES):
    _YEAR_CODES[_code] = 2010 + _offset

# WMI (World Manufacturer Identifier) prefix -> brand. Only a tiny demo map;
# anything unknown stays "unknown" and simply contributes no brand evidence.
_WMI_BRANDS: dict[str, str] = {
    "WBA": "BMW",
    "WBS": "BMW",
    "WBY": "BMW",
    "WAR": "BMW",
    "WA1": "Audi",
    "WAU": "Audi",
    "WUA": "Audi",
    "WVG": "Volkswagen",
    "WVW": "Volkswagen",
    "3VW": "Volkswagen",
    "ZAR": "Alfa Romeo",
    "JHM": "Honda",
    "JTD": "Toyota",
    "JT1": "Toyota",
    "JM1": "Mazda",
    "KMH": "Hyundai",
    "KNA": "Kia",
    "TMB": "Škoda",
    "VF3": "Peugeot",
    "VF1": "Renault",
    "VS1": "Opel",
    "WOL": "Opel",
    "YV1": "Volvo",
    "SAL": "Land Rover",
    "XLR": "Volvo",
    "1HD": "Harley-Davidson",
}

_VALID_VIN_CHARS = frozenset("0123456789ABCDEFGHJKLMNPRSTUVWXYZ")


@dataclass
class VinDecode:
    """Result of decoding a VIN (ISO 3779, 17 chars)."""

    valid: bool
    brand: str = ""
    year: int | None = None
    reason: str = ""


def normalize_vin(raw: str | None) -> str:
    if not raw:
        return ""
    return "".join(ch for ch in raw.upper() if ch in _VALID_VIN_CHARS)


def check_digit(vin: str) -> str | None:
    """The ISO 3779 check digit for a 17-char VIN, or None if not decodable."""
    if len(vin) != 17:
        return None
    total = 0
    for i, char in enumerate(vin):
        weight = _VIN_POSITION_WEIGHTS[i]
        if weight == 0:
            continue
        if char not in _VIN_TRANSLITERATION:
            return None
        total += _VIN_TRANSLITERATION[char] * weight
    remainder = total % 11
    return "X" if remainder == 10 else str(remainder)


def decode_vin(raw: str | None) -> VinDecode:
    """Decode a VIN: validate, extract brand (WMI) and model year (pos 10)."""
    vin = normalize_vin(raw)
    if len(vin) != 17:
        return VinDecode(valid=False, reason="VIN должен содержать 17 символов")
    if vin[8] != check_digit(vin):
        return VinDecode(valid=False, reason="VIN не прошёл контрольную сумму")
    brand = _WMI_BRANDS.get(vin[:3], "")
    year = _YEAR_CODES.get(vin[9])
    return VinDecode(valid=True, brand=brand, year=year)


def brand_from_vin(raw: str | None) -> str:
    return decode_vin(raw).brand
