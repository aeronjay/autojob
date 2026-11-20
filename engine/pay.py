"""Turn free-text pay ("$5-$7/hour", "PHP 70,000", "1000") into USD per month so jobs can be compared.

It's an estimate: hourly rates assume full-time hours, and bare numbers are guessed by size.
Returns (low, high) in whole USD per month, or (None, None) when the text has no usable figure.
"""
import re

# Rough conversion to USD. Override any of these under [pay.rates] in config.toml.
RATES = {"usd": 1.0, "php": 1 / 58, "aud": 0.65, "cad": 0.72, "gbp": 1.27, "eur": 1.08, "sgd": 0.75, "inr": 0.012, "pln": 0.25}

CURRENCIES = [
    ("usd", r"usd|us\$"),
    ("php", r"php|₱|peso|\bp\d"),
    ("inr", r"inr|₹|rupee"),
    ("sgd", r"sgd|s\$"),
    ("aud", r"aud|au?\$"),
    ("cad", r"cad|ca?\$"),
    ("gbp", r"gbp|£"),
    ("eur", r"eur|€"),
    ("pln", r"pln|zł"),
]

PERIODS = [
    ("hour", r"/\s*h\b|/\s*hr|\bhrs?\b|hour|\bph\b"),
    ("month", r"mont|mth|/\s*mo\b|\bmo\b|/\s*m\b|\bpm\b"),
    ("year", r"year|annual|annum|/\s*yr|\byr\b|p\.a"),
    ("week", r"week|/\s*wk|\bwk\b"),
    ("day", r"/\s*day|per day|a day|daily"),
    # "per video", "per completed reel"...: piece rates can't be compared with a salary.
    ("project", r"project|fixed|one[- ]time|per (?!hour|hr|h\b|month|mo\b|year|annum|week|day|sale)"),
]

NUMBER = re.compile(r"(\d+(?:\.\d+)?)\s*(k(?=php|\b))?")
RANGE_GAP = re.compile(r"^[\s$₱£€₹?a-z]{0,8}(-|\bto\b)[\s$₱£€₹?a-z]{0,8}$")


def parse(text, source="", pay_cfg=None):
    pay_cfg = pay_cfg or {}
    t = str(text or "").lower().replace("–", "-").replace("—", "-")
    t = re.sub(r"(?<=\d)[,.](?=\d{3}(?!\d))", "", t)  # thousands separators: "1,800" and "1.800"
    t = re.sub(r"\d+\s*(?:-\s*\d+\s*)?(?:hrs?|hours)\s*(?:/|per|a)\s*(?:week|wk|day)", " ", t)  # "20 hrs/week" isn't pay
    nums = list(NUMBER.finditer(t))
    if not nums:
        return None, None
    start, first = 0, nums[0]
    lo = float(first.group(1)) * (1000 if first.group(2) else 1)
    hi = lo
    if start + 1 < len(nums):
        second = nums[start + 1]
        if RANGE_GAP.match(t[first.end():second.start()]):
            hi = float(second.group(1)) * (1000 if second.group(2) else 1)
            if hi >= lo * 100:  # "1.5-2k", "120-140,000": the first figure is in thousands too
                lo *= 1000
    if hi < lo:
        hi = lo

    # The currency named first wins: "Php 48,852/mo ($900 USD)" is pesos.
    named = [(m.start(), name) for name, rx in CURRENCIES if (m := re.search(rx, t))]
    currency = min(named)[1] if named else None
    after = t[first.start():]
    found = [(m.start(), name) for name, rx in PERIODS if (m := re.search(rx, after))]
    period = min(found)[1] if found else None
    if period == "project":
        return None, None

    # OnlineJobs.ph employers often type peso amounts with no currency ("40,000 per month").
    if currency is None and source == "onlinejobs" and period in (None, "month") and lo >= 15000:
        currency, period = "php", "month"
    if currency is None and source == "onlinejobs" and period is None and lo >= 5000:
        return None, None  # "12000" alone could be pesos or dollars; don't guess
    if period is None:  # bare number: guess from its size
        if currency == "php":
            period = "year" if lo >= 400000 else "month" if lo >= 5000 else "day" if lo >= 300 else "hour"
        else:
            period = "hour" if lo < 50 else "month" if lo < 15000 else "year"

    rate = {**RATES, **pay_cfg.get("rates", {})}.get(currency or "usd", 1.0)
    per_month = {"hour": pay_cfg.get("hours_per_month", 160), "day": 22, "week": 4.33, "month": 1, "year": 1 / 12}[period]
    lo, hi = (round(x * rate * per_month) for x in (lo, hi))
    if hi < 30 or hi > 60000:  # not a believable salary; probably some other number
        return None, None
    return lo, hi
