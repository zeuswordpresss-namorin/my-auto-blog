# -*- coding: utf-8 -*-
import xml.etree.ElementTree as ET
import requests
import json
from config import TRENDS_RSS_URLS, GOOGLE_AUTOCOMPLETE_URL, MAX_TRENDS_COUNT

def fetch_google_trends() -> list:
    """구글 트렌드 RSS 피드에서 인기 검색어를 가져옵니다."""
    for url in TRENDS_RSS_URLS:
        try:
            resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            titles = [item.findtext("title") for item in root.iter("item")]
            keywords = [t.strip() for t in titles if t and t.strip()]
            if keywords:
                return keywords[:MAX_TRENDS_COUNT]
        except Exception as e:
            print(f"[경고] {url} 수집 실패: {e}")
    return []

def fetch_google_autocomplete(seed_keywords: list) -> list:
    """수집된 트렌드 키워드를 기반으로 구글 자동완성 연관 검색어를 확장합니다."""
    extended = []
    for kw in seed_keywords[:3]:  # 상위 3개 키워드 위주로 확장
        try:
            params = {"q": kw, "hl": "ko", "client": "firefox"}
            resp = requests.get(GOOGLE_AUTOCOMPLETE_URL, params=params, timeout=5)
            if resp.status_code == 200:
                data = json.loads(resp.text)
                if len(data) > 1:
                    extended.extend(data[1][:3])  # 연관어 최대 3개씩 확보
        except Exception as e:
            print(f"[경고] 자동완성 수집 실패 ({kw}): {e}")
    return extended

