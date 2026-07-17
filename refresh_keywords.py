# -*- coding: utf-8 -*-
"""
프로젝트명: 주간 키워드 자동 보충 및 스코어링 시스템
파일 역할: 단일 통합 핵심 컨트롤러 (refresh_keywords.py)
"""

import json
import os
import re
import xml.etree.ElementTree as ET
import requests

try:
    import config
except ImportError:
    class DummyConfig:
        QUEUE_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "keywords_queue.json")
        TRENDS_RSS_URLS = [
            "https://trends.google.com/trending/rss?geo=KR",
            "https://trends.google.com/trends/trendingsearches/daily/rss?geo=KR"
        ]
        GOOGLE_AUTOCOMPLETE_URL = "https://suggestqueries.google.com/complete/search"
        MAX_TRENDS_COUNT = 7
        MIN_KEYWORD_LENGTH = 2
        MAX_KEYWORD_LENGTH = 30
        BANNED_WORDS = ["토토", "카지노", "성인", "몰카", "불법", "마약", "조건만남"]
        SCORE_WEIGHTS = {"trend_rank": 0.4, "source_bonus": 0.3, "cpc_bonus": 0.3}
        CPC_BONUS_WORDS = {"대출": 30.0, "보험": 30.0, "카드": 20.0, "주식": 15.0, "정부지원금": 25.0}
    config = DummyConfig()

def fetch_google_trends() -> list:
    for url in config.TRENDS_RSS_URLS:
        try:
            resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            titles = [item.findtext("title") for item in root.iter("item")]
            keywords = [t.strip() for t in titles if t and t.strip()]
            if keywords:
                return keywords[:config.MAX_TRENDS_COUNT]
        except Exception as e:
            print(f"[경고] 트렌드 수집 실패 ({url}): {e}")
    return []

def fetch_google_autocomplete(seed_keywords: list) -> list:
    extended = []
    for kw in seed_keywords[:3]:
        try:
            params = {"q": kw, "hl": "ko", "client": "firefox"}
            resp = requests.get(config.GOOGLE_AUTOCOMPLETE_URL, params=params, timeout=5)
            if resp.status_code == 200:
                data = json.loads(resp.text)
                if len(data) > 1:
                    extended.extend(data[1][:3])
        except Exception as e:
            print(f"[경고] 자동완성 수집 실패 ({kw}): {e}")
    return extended

def normalize_keyword(kw: str) -> str:
    kw = re.sub(r'\s+', ' ', kw)
    return kw.strip()

def is_valid_keyword(kw: str) -> bool:
    if not kw or len(kw) < config.MIN_KEYWORD_LENGTH or len(kw) > config.MAX_KEYWORD_LENGTH:
        return False
    for banned in config.BANNED_WORDS:
        if banned in kw:
            return False
    return True

def get_cpc_score(kw: str) -> float:
    score = 0.0
    for word, bonus in config.CPC_BONUS_WORDS.items():
        if word in kw:
            score += bonus
    return score

def calculate_total_score(kw: str, rank_idx: int, is_trend: bool, is_auto: bool) -> float:
    rank_score = (10 - rank_idx) * 10 if rank_idx < 10 else 10
    if not is_trend:
        rank_score = 0
    source_score = 100.0 if (is_trend and is_auto) else 50.0
    cpc_score = get_cpc_score(kw)
    total = (
        (rank_score * config.SCORE_WEIGHTS["trend_rank"]) +
        (source_score * config.SCORE_WEIGHTS["source_bonus"]) +
        (cpc_score * config.SCORE_WEIGHTS["cpc_bonus"])
    )
    return round(total, 2)

def load_queue() -> dict:
    default_structure = {"pending": [], "completed": []}
    if not os.path.exists(config.QUEUE_FILE_PATH):
        return default_structure
    try:
        with open(config.QUEUE_FILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "pending" in data and "completed" in data:
                return data
            return default_structure
    except Exception:
        return default_structure

def save_queue(queue: dict) -> None:
    with open(config.QUEUE_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)

def main():
    print("[시스템] 올인원 키워드 파이프라인 시작...")
    queue = load_queue()
    existing_keywords = set(queue["pending"]) | set(queue["completed"])
    
    trends = fetch_google_trends()
    autocompletes = fetch_google_autocomplete(trends)
    
    candidates = {}
    for idx, kw in enumerate(trends):
        norm_kw = normalize_keyword(kw)
        if is_valid_keyword(norm_kw) and norm_kw not in existing_keywords:
            candidates[norm_kw] = {"rank_idx": idx, "is_trend": True, "is_auto": False}
            
    for kw in autocompletes:
        norm_kw = normalize_keyword(kw)
        if is_valid_keyword(norm_kw) and norm_kw not in existing_keywords:
            if norm_kw in candidates:
                candidates[norm_kw]["is_auto"] = True
            else:
                candidates[norm_kw] = {"rank_idx": 99, "is_trend": False, "is_auto": True}
                
    scored_list = []
    for kw, info in candidates.items():
        score = calculate_total_score(kw, info["rank_idx"], info["is_trend"], info["is_auto"])
        scored_list.append((kw, score))
        
    scored_list.sort(key=lambda x: x[1], reverse=True)
    new_sorted_keywords = [item[0] for item in scored_list]
    
    queue["pending"].extend(new_sorted_keywords)
    save_queue(queue)
    print(f"[완료] 현재 pending 리스트 총 수량: {len(queue['pending'])}개")

if __name__ == "__main__":
    main()
