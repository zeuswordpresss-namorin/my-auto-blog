# -*- coding: utf-8 -*-
import json
import os
from config import QUEUE_FILE_PATH
import keyword_sources
import keyword_filters
import keyword_scoring

def load_queue() -> dict:
    """큐 파일을 읽어옵니다. 파일이 없거나 깨졌다면 요구 사양 구조를 리턴합니다."""
    default_structure = {"pending": [], "completed": []}
    if not os.path.exists(QUEUE_FILE_PATH):
        return default_structure
    try:
        with open(QUEUE_FILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "pending" in data and "completed" in data:
                return data
            return default_structure
    except Exception:
        return default_structure

def save_queue(queue: dict) -> None:
    """큐 파일을 UTF-8 안전 포맷으로 저장합니다."""
    with open(QUEUE_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)

def run_pipeline():
    print("[시스템] 키워드 파이프라인 가동...")
    
    # 1. 기존 데이터 로드
    queue = load_queue()
    existing_keywords = set(queue["pending"]) | set(queue["completed"])
    
    # 2. 소스로부터 날 것의 데이터 수집
    trends = keyword_sources.fetch_google_trends()
    autocompletes = keyword_sources.fetch_google_autocomplete(trends)
    
    # 3. 데이터 통합 및 분석/필터/정규화/스코어링
    candidates = {}
    
    # 트렌드 키워드 반영
    for idx, kw in enumerate(trends):
        norm_kw = keyword_filters.normalize_keyword(kw)
        if keyword_filters.is_valid_keyword(norm_kw) and norm_kw not in existing_keywords:
            candidates[norm_kw] = {"rank_idx": idx, "is_trend": True, "is_auto": False}
            
    # 자동완성 키워드 병합 및 반영
    for kw in autocompletes:
        norm_kw = keyword_filters.normalize_keyword(kw)
        if keyword_filters.is_valid_keyword(norm_kw) and norm_kw not in existing_keywords:
            if norm_kw in candidates:
                candidates[norm_kw]["is_auto"] = True
            else:
                candidates[norm_kw] = {"rank_idx": 99, "is_trend": False, "is_auto": True}
                
    # 4. 종합 스코어링 및 정렬
    scored_list = []
    for kw, info in candidates.items():
        score = keyword_scoring.calculate_total_score(
            kw, info["rank_idx"], info["is_trend"], info["is_auto"]
        )
        scored_list.append((kw, score))
        
    # 점수 높은 순 정렬
    scored_list.sort(key=lambda x: x[1], reverse=True)
    new_sorted_keywords = [item[0] for item in scored_list]
    
    # 5. 큐에 결합 및 저장
    queue["pending"].extend(new_sorted_keywords)
    save_queue(queue)
    
    print(f"[완료] 새롭게 필터링/스코어링되어 추가된 키워드: {new_sorted_keywords}")
    print(f"[결과] 현재 pending 큐 수량: {len(queue['pending'])}개")

if __name__ == "__main__":
    run_pipeline()
