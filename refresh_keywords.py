# -*- coding: utf-8 -*-
"""
프로젝트명: 주간 키워드 자동 보충 및 스코어링 시스템
파일 역할: 단일 통합 핵심 컨트롤러 (refresh_keywords.py)
기능: 수집, 필터링, CPC 스코어링, 큐 정렬 및 저장 올인원 처리
"""

import json
import os
import re
import xml.etree.ElementTree as ET
import requests

# config.py 설정값 로드
try:
    import config
except ImportError:
    # config.py가 없을 경우를 대비한 가이드라인 기본값 선언
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

# ==========================================
# 1. 데이터 수집 모듈 (Sources)
# ==========================================
def fetch_google_trends() -> list:
    """구글 트렌드 RSS 피드에서 인기 검색어를 수집합니다."""
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
    """트렌드 키워드를 기반으로 연관 자동완성 키워드를 확장합니다."""
    extended = []
    for kw in seed_keywords[:3]:  # 상위 3개 키워드로 확장 진행
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

# ==========================================
# 2. 데이터 필터링 모듈 (Filters)
# ==========================================
def normalize_keyword(kw: str) -> str:
    """공백 정규화 및 문자열 정제를 처리합니다."""
    kw = re.sub(r'\s+', ' ', kw)
    return kw.strip()

def is_valid_keyword(kw: str) -> bool:
    """길이 및 금지어 기반 검증을 수행합니다."""
    if not kw or len(kw) < config.MIN_KEYWORD_LENGTH or len(kw) > config.MAX_KEYWORD_LENGTH:
        return False
    for banned in config.BANNED_WORDS:
        if banned in kw:
            return False
    return True

# ==========================================
# 3. 스코어링 엔진 모듈 (Scoring)
# ==========================================
def get_cpc_score(kw: str) -> float:
    """고단가(CPC) 단어 포함 여부에 따른 보너스 점수를 반환합니다."""
    score = 0.0
    for word, bonus in config.CPC_BONUS_WORDS.items():
        if word in kw:
            score += bonus
    return score

def calculate_total_score(kw: str, rank_idx: int, is_trend: bool, is_auto: bool) -> float:
    """트렌드 순위, 출처 시너지, CPC 보너스를 종합하여 최종 점수를 도출합니다."""
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

# ==========================================
# 4. 파일 입출력 및 메인 파이프라인 (Queue Manager)
# ==========================================
def load_queue() -> dict:
    """큐 파일을 읽어옵니다. 파일이 없거나 오류 발생 시 표준 구조를 보장합니다."""
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
    """최종 결과 데이터를 JSON 규격에 맞춰 안전하게 저장합니다."""
    with open(config.QUEUE_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)

def main():
    print("[시스템] 올인원 키워드 파이프라인 시작...")
    
    # 1. 기존 데이터 적재 및 중복 방지 셋 구성
    queue = load_queue()
    existing_keywords = set(queue["pending"]) | set(queue["completed"])
    
    # 2. 수집 가동
    trends = fetch_google_trends()
    autocompletes = fetch_google_autocomplete(trends)
    
    # 3. 가공 및 스코어링 매핑
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
                
    # 4. 종합 스코어 기반 정렬
    scored_list = []
    for kw, info in candidates.items():
        score = calculate_total_score(kw, info["rank_idx"], info["is_trend"], info["is_auto"])
        scored_list.append((kw, score))
        
    scored_list.sort(key=lambda x: x[1], reverse=True)
    new_sorted_keywords = [item[0] for item in scored_list]
    
    # 5. 기존 pending 리스트에 추가 및 파일 저장
    queue["pending"].extend(new_sorted_keywords)
    save_queue(queue)
    
    print(f"[완료] 필터링 및 CPC 정렬을 거쳐 새롭게 추가된 키워드: {new_sorted_keywords}")
    print(f"[결과] 현재 pending 리스트 총 수량: {len(queue['pending'])}개")

if __name__ == "__main__":
    main()
