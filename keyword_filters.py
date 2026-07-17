# -*- coding: utf-8 -*-
import re
from config import MIN_KEYWORD_LENGTH, MAX_KEYWORD_LENGTH, BANNED_WORDS

def normalize_keyword(kw: str) -> str:
    """공백 정규화 및 불필요한 특수문자를 제거합니다."""
    kw = re.sub(r'\s+', ' ', kw)
    return kw.strip()

def is_valid_keyword(kw: str) -> bool:
    """길이 및 금지어 목록을 기준으로 필터링을 수행합니다."""
    if not kw or len(kw) < MIN_KEYWORD_LENGTH or len(kw) > MAX_KEYWORD_LENGTH:
        return False
    for banned in BANNED_WORDS:
        if banned in kw:
            return False
    return True

