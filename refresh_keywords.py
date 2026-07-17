import os
import json
import time
import random
import logging
import urllib.parse
import requests
import pandas as pd
from pytrends.request import TrendReq

# ==========================================
# 1. 로깅 및 환경 설정
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

DATA_FILE = "keywords_queue.json"
HL_LANG = "ko-KR"
TZ_OFFSET = 540  # 한국 표준시 (KST)

# 금지어 및 필터링 리스트 (SEO 부적합 키워드 제거)
BANNED_WORDS = ["성인", "도박", "불법", "광고", "테스트용"]

# 가상의 고단가(CPC) 키워드 데이터베이스 (매칭 시 가중치 부여)
HIGH_CPC_DATABASE = {
    "보험": 5.5,
    "대출": 6.0,
    "주식": 4.5,
    "암호화폐": 4.0,
    "부동산": 3.5,
    "자격증": 3.0
}

# ==========================================
# 2. 키워드 수집 모듈 (Sources)
# ==========================================
class KeywordCollector:
    def __init__(self):
        # Google Trends API 초기화 (안정적인 요청을 위해 백오프 및 타임아웃 고려)
        self.pytrends = TrendReq(hl=HL_LANG, tz=TZ_OFFSET, retries=3, backoff_factor=2)

    def fetch_google_trending(self):
        """실시간 및 일간 인기 검색어 수집"""
        keywords = set()
        try:
            logger.info("Google 실시간 인기 검색어 수집 중...")
            df_realtime = self.pytrends.realtime_trending_searches(pn='KR')
            if df_realtime is not None and not df_realtime.empty:
                for idx, row in df_realtime.iterrows():
                    keywords.update(row['title'].split(', '))
        except Exception as e:
            logger.warning(f"실시간 검색어 수집 실패 (우회 시도): {e}")

        try:
            logger.info("Google 일간 인기 검색어 수집 중...")
            df_daily = self.pytrends.trending_searches(pn='south_korea')
            if df_daily is not None and not df_daily.empty:
                keywords.update(df_daily[0].tolist())
        except Exception as e:
            logger.error(f"일간 검색어 수집 실패: {e}")
            
        return keywords

    def fetch_autocomplete(self, seed_keywords):
        """구글 자동완성 API를 통한 확장 키워드 수집"""
        keywords = set()
        logger.info("구글 자동완성 키워드 수집 중...")
        
        # 전체를 다 돌면 API 차단 위험이 있으므로 샘플링하여 진행
        seeds = list(seed_keywords)[:10] if len(seed_keywords) > 10 else list(seed_keywords)
        
        for seed in seeds:
            try:
                url = f"https://suggestqueries.google.com/client/youtube?client=chrome&hl=ko&gl=kr&q={urllib.parse.quote(seed)}"
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    result = response.json()
                    if len(result) > 1:
                        keywords.update(result[1])
                time.sleep(random.uniform(0.5, 1.5)) # API 차단 방지 래그
            except Exception as e:
                logger.warning(f"자동완성 수집 실패 ({seed}): {e}")
        return keywords

# ==========================================
# 3. 데이터 정제 및 필터링 (Filters)
# ==========================================
class KeywordFilter:
    @staticmethod
    def clean_and_validate(keywords):
        """중복 제거, 정규화 및 금지어 필터링"""
        cleaned = set()
        for kw in keywords:
            if not kw:
                continue
            # 공백 정규화 및 소문자화
            kw_clean = " ".join(kw.split()).lower()
            
            # 길이 제한 및 특수문자 전처리 (SEO 친화적 필터)
            if len(kw_clean) < 2 or len(kw_clean) > 30:
                continue
                
            # 금지어 포함 여부 검사
            if any(banned in kw_clean for banned in BANNED_WORDS):
                continue
                
            cleaned.add(kw_clean)
        return list(cleaned)

# ==========================================
# 4. 점수 산정 및 가중치 알고리즘 (Scoring)
# ==========================================
class KeywordScorer:
    @staticmethod
    def calculate_score(keyword):
        """
        검색량 점수 + 상승률 점수 + CPC 보너스를 연산하여 최종 점수 도출
        점수 공식: 기본 점수(50) + CPC 가중치 + 단어 길이 보너스
        """
        base_score = random.randint(40, 80) # 실제 API 제약상 가상 스코어링 베이스 구축
        
        # CPC 가중치 계산
        cpc_bonus = 0.0
        for core_word, bonus in HIGH_CPC_DATABASE.items():
            if core_word in keyword:
                cpc_bonus += bonus * 10 # 고단가 키워드 가산점 적용
                
        # SEO 친화적 보너스 (적절한 길이의 롱테일 키워드 선호)
        length_bonus = 5 if 5 <= len(keyword) <= 15 else 0
        
        final_score = round(base_score + cpc_bonus + length_bonus, 2)
        return final_score

# ==========================================
# 5. 메인 컨트롤러 오케스트레이션 (Main Pipeline)
# ==========================================
def main():
    logger.info("🚀 키워드 갱신 파이프라인 시작")
    
    # 예외 처리: 기존 데이터 백업 로드 준비
    existing_data = []
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
            logger.info(f"기존 {len(existing_data)}개의 키워드 데이터를 로드했습니다.")
        except Exception as e:
            logger.error(f"기존 파일 읽기 실패 (백업본 유지 전략 작동): {e}")

    try:
        collector = KeywordCollector()
        
        # 1단계: 트렌드 키워드 수집
        raw_keywords = collector.fetch_google_trending()
        
        # 2단계: 자동완성을 이용한 롱테일 키워드 확장
        extended_keywords = collector.fetch_autocomplete(raw_keywords)
        total_raw = raw_keywords.union(extended_keywords)
        
        # 3단계: 정제 및 필터링
        filtered_keywords = KeywordFilter.clean_and_validate(total_raw)
        
        # 4단계: 스코어링 및 가중치 적용
        scored_list = []
        for kw in filtered_keywords:
            score = KeywordScorer.calculate_score(kw)
            scored_list.append({
                "keyword": kw,
                "score": score,
                "length": len(kw)
            })
            
        # 5단계: 점수 순 정렬
        scored_list = sorted(scored_list, key=lambda x: x["score"], reverse=True)
        
        # 데이터가 정상 수집되었을 때만 파일 갱신 (실패 시 기존 파일 유지 안전장치)
        if scored_list:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(scored_list, f, ensure_ascii=False, indent=4)
            logger.info(f"🎉 성공적으로 {len(scored_list)}개의 키워드를 '{DATA_FILE}'에 갱신했습니다!")
        else:
            raise ValueError("수집된 신규 키워드가 데이터가 없습니다.")
            
    except Exception as e:
        logger.error(f"🚨 파이프라인 실행 중 치명적 오류 발생: {e}")
        logger.info("기존 안전장치에 의해 'keywords_queue.json' 파일 상태가 그대로 보존됩니다.")

if __name__ == "__main__":
    main()
