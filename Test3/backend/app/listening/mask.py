from __future__ import annotations

import hashlib
import hmac
import re

PHONE = re.compile(r"1[3-9]\d{9}")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
IDCARD = re.compile(r"\d{17}[\dXx]")
STUDENT = re.compile(r"(?<!\d)(?:20\d{2}|19\d{2})\d{6,10}(?!\d)")
NAME = re.compile(r"(?:我是|我叫|同学)([一-龥]{2,3})")


def mask_text(text: str) -> str:
    out = PHONE.sub("[PHONE]", text)
    out = EMAIL.sub("[EMAIL]", out)
    out = IDCARD.sub("[IDCARD]", out)
    out = STUDENT.sub("[STUDENT_ID]", out)
    out = NAME.sub(lambda m: m.group(0).replace(m.group(1), "[NAME]"), out)
    return out


def hash_author(author: str, key: str) -> str:
    if not key:
        raise ValueError("FEEDBACK_HASH_KEY missing")
    return hmac.new(key.encode("utf-8"), author.encode("utf-8"), hashlib.sha256).hexdigest()


def contains_raw_secrets(masked: str, original: str) -> bool:
    for match in PHONE.findall(original) + EMAIL.findall(original):
        if match in masked:
            return True
    return False
