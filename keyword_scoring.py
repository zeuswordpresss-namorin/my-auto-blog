# -*- coding: utf-8 -*-
"""
프로젝트명: 주간 키워드 자동 보충 및 스코어링 시스템
파일 역할: 키워드 CPC 보너스 산출 및 종합 스코어링 엔진 (keyword_scoring.py)
"""

from config import CPC_BONUS_WORDS, SCORE_WEIGHTS

def get_cpc_score(kw: str) -> float:
    """
    키워드 내에 고단가(CPC) 보너스 단어가 포함되어 있는지 검사하여 
    누적된 보너스 점수를 반환합니다.
    """
    score = 0.0
    for word, bonus in CPC_BONUS_WORDS.items():
        if word in kw:
            score += bonus
    return score

def calculate_total_score(kw: str, rank_idx: int, is_trend: bool, is_auto: bool) -> float:
    """
    구글 트렌드 순위 점수, 출처 다양성 점수, CPC 보너스 점수를 
    config.py에 정의된 가중치(WEIGHTS) 비율에 맞춰 결합하여 최종 점수를 산출합니다.
    """
    # 1. 트렌드 순위 점수 계산 (1위=100점, 2위=90점 ... 순위권 밖=10점)
    rank_score = (10 - rank_idx) * 10 if rank_idx < 10 else 10
    if not is_trend: 
        rank_score = 0
    
    # 2. 소스 다양성 점수 계산 (두 채널 모두에서 발견되면 100점 만점 시너지)
    source_score = 0.0
    if is_trend and is_auto: 
        source_score = 100.0
    elif is_trend or is_auto: 
        source_score = 50.0
    
    # 3. 고단가 가중치 점수 계산
    cpc_score = get_cpc_score(kw)
    
    # 4. 가중치를 반영한 최종 종합 점수 도출
    total = (
        (rank_score * SCORE_WEIGHTS["trend_rank"]) +
        (source_score * SCORE_WEIGHTS["source_bonus"]) +
        (cpc_score * SCORE_WEIGHTS["cpc_bonus"])
    )
    
    # 소수점 둘째 자리까지 반올림하여 반환
    return round(total, 2)

