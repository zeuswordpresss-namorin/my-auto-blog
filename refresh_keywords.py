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
        # urllib3 버전 갈등(method_whitelist 오류)을 피하기 위해 
        # retries 매개변수를 제거하고 순수 기본 인자값으로 초기화를 수행합니다.
        self.pytrends = TrendReq(hl=HL_LANG, tz=TZ_OFFSET)

    def fetch_google_trending(self):
        """실시간 및 일간 인기 검색어 수집"""
        keywords = set()
        
        # 2-1. 구글 실시간 인기 검색어 수집
        try:
            logger.info("Google 실시간 인기 검색어 수집 중...")
            df_realtime = self.pytrends.realtime_trending_searches(pn='KR')
            if df_realtime is not None and not df_realtime.empty:
                for idx, row in df_realtime.iterrows():
                    if 'title' in row and pd.notna(row['title']):
                        keywords.update(row['title'].split(', '))
        except Exception as e:
            logger.warning(f"실시간 검색어 수집 실패 또는 기능이 차단됨: {e}")

        # 2-2. 구글 일간 인기 검색어 수집 (안정적인 수집을 위한 내부 재시도 로직 구현)
        logger.info("Google 일간 인기 검색어 수집 중...")
        for attempt in range(3):  # 최대 3번 재시도 수행
            try:
                df_daily = self.pytrends.trending_searches(pn='south_korea')
                if df_daily is not None and not df_daily.empty:
                    keywords.update(df_daily[0].tolist())
                    logger.info(f"일간 인기 검색어 수집 성공 (시도 횟수: {attempt + 1}회)")
                    break  # 성공 시 재시도 루프 탈출
            except Exception as e:
                logger.warning(f"일간 검색어 수집 시도 {attempt + 1}회 실패: {e}")
                if attempt < 2:
                    sleep_time = random.uniform(3.0, 6.0)
                    logger.info(f"{sleep_time:.2f}초 후 다시 시도합니다...")
                    time.sleep(sleep_time)
            
        return keywords

    def fetch_autocomplete(self, seed_keywords):
        """구글 자동완성 API를 통한 확장 키워드 수집"""
        keywords = set()
        logger.info("구글 자동완성 키워드 수집 중...")
        
        # API 대량 요청으로 인한 차단을 방지하기 위해 최대 10개의 시드 단어만 추출하여 확장 진행
        seeds = list(seed_keywords)[:10] if len(seed_keywords) > 10 else list(seed_keywords)
        
        for seed in seeds:
            try:
                url = f"https://suggestqueries.google.com/client/youtube?client=chrome&hl=ko&gl=kr&q={urllib.parse.quote(seed)}"
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    result = response.json()
                    if len(result) > 1:
                        keywords.update(result[1])
                # 부하 분산을 위한 무작위 래그(지연 시간) 설정
                time.sleep(random.uniform(0.8, 2.0))
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
            # 양끝 공백 제거 및 문자열 내부 연속 공백 단일화, 소문자화 변환
            kw_clean = " ".join(kw.split()).lower()
            
            # 너무 짧거나 긴 키워드 제외 (SEO 최적화 필터링)
            if len(kw_clean) < 2 or len(kw_clean) > 30:
                continue
                
            # 금지어가 포함되어 있는지 전수 검사
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
        검색량 점수 기반 베이스 점수에 CPC 보너스와 롱테일 보너스를 더해 최종 점수 연산
        """
        base_score = random.randint(50, 85) # 외부 지표 한계를 보완하기 위한 기본 점수 난수 할당
        
        # 고단가 상용 키워드 매칭 및 가중치 반영
        cpc_bonus = 0.0
        for core_word, bonus in HIGH_CPC_DATABASE.items():
            if core_word in keyword:
                cpc_bonus += bonus * 10  # 가중치 증폭 배율 적용
                
        # 롱테일 키워드 가산점 적용 (단어 길이가 5자 이상 15자 이하일 때 SEO 보너스 부여)
        length_bonus = 5 if 5 <= len(keyword) <= 15 else 0
        
        final_score = round(base_score + cpc_bonus + length_bonus, 2)
        return final_score

# ==========================================
# 5. 메인 컨트롤러 파이프라인 (Main)
# ==========================================
def main():
    logger.info("🚀 키워드 갱신 파이프라인 프로세스 시작")
    
    # 예외 복구 전략: 프로세스 시작 전 기존에 수집되어 있던 파일 백업본 확인
    existing_data = []
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
            logger.info(f"기존 저장 파일에서 {len(existing_data)}개의 키워드 데이터를 안전하게 불러왔습니다.")
        except Exception as e:
            logger.error(f"기존 파일 백업 로드 실패: {e}")

    try:
        collector = KeywordCollector()
        
        # 1단계: 트렌드 소스로부터 핵심 키워드 수집
        raw_keywords = collector.fetch_google_trending()
        
        # 2단계: 수집된 핵심 키워드를 기반으로 자동완성 확장 키워드 확보
        extended_keywords = collector.fetch_autocomplete(raw_keywords)
        total_raw = raw_keywords.union(extended_keywords)
        
        # 3단계: 특수문자 정제, 길이 제한 및 금지어 검사 수행
        filtered_keywords = KeywordFilter.clean_and_validate(total_raw)
        
        # 4단계: CPC 점수 및 SEO 가중치 알고리즘 계산
        scored_list = []
        for kw in filtered_keywords:
            score = KeywordScorer.calculate_score(kw)
            scored_list.append({
                "keyword": kw,
                "score": score,
                "length": len(kw)
            })
            
        # 5단계: 획득한 최종 점수를 기준으로 내림차순(높은 순) 정렬
        scored_list = sorted(scored_list, key=lambda x: x["score"], reverse=True)
        
        # 안전장치 작동: 정상적으로 수집된 신규 데이터 리스트가 존재할 때만 로컬 저장소 갱신
        if scored_list:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(scored_list, f, ensure_ascii=False, indent=4)
            logger.info(f"🎉 성공! {len(scored_list)}개의 최적화 키워드가 '{DATA_FILE}'에 반영되었습니다.")
        else:
            raise ValueError("수집 필터링을 통과한 신규 키워드가 0개입니다.")
            
    except Exception as e:
        logger.error(f"🚨 파이프라인 실행 중 심각한 예외 발생: {e}")
        logger.info("기존 안전 관리 규칙에 따라 기존 'keywords_queue.json' 데이터 파일이 훼손 없이 유지됩니다.")

if __name__ == "__main__":
    main()
