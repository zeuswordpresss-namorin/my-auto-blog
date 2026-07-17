import os
import json
import time
import random
import logging
import urllib.parse
import xml.etree.ElementTree as ET
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
# 2. 키워드 수집 모듈 (Sources) - 404 오류 우회 버전
# ==========================================
class KeywordCollector:
    def __init__(self):
        self.pytrends = TrendReq(hl=HL_LANG, tz=TZ_OFFSET)
        # 구글 트렌드 공식 RSS 피드 주소 (국가 코드: KR)
        self.rss_url = "https://trends.google.co.kr/trending/rss?geo=KR"

    def fetch_google_trending(self):
        """인기 검색어 수집 (API 404 발생 시 RSS 피드로 강제 우회)"""
        keywords = set()
        
        # [시도 1] 기존 pytrends API 접근
        try:
            logger.info("구글 API를 통해 인기 검색어 수집을 시도합니다...")
            df_daily = self.pytrends.trending_searches(pn='south_korea')
            if df_daily is not None and not df_daily.empty:
                keywords.update(df_daily[0].tolist())
                logger.info("구글 API 수집 성공!")
                return keywords
        except Exception as e:
            logger.warning(f"구글 API 접근 실패 (404 등 오류 발생): {e}")
            logger.info("안전한 우회로인 '구글 트렌드 RSS 피드' 수집으로 전환합니다.")

        # [시도 2] API 실패 시 RSS 피드 파싱 (GitHub Actions 환경 최적화)
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            response = requests.get(self.rss_url, headers=headers, timeout=10)
            if response.status_code == 200:
                # XML 데이터 파싱
                root = ET.fromstring(response.text)
                for item in root.findall('.//item'):
                    title = item.find('title')
                    if title is not None and title.text:
                        keywords.add(title.text.strip())
                        
                    # 연관 검색어(approx_traffic 등) 추가 파싱
                    approx_query = item.find('{https://trends.google.co.kr/trending/rss}approx_traffic')
                    # 확장 태그가 잡히지 않을 경우 기본 제목 위주로 수집 진행
                logger.info(f"구글 RSS 피드 우회 수집 성공! ({len(keywords)}개 확보)")
            else:
                logger.error(f"구글 RSS 피드 접근 실패 (HTTP 상태 코드: {response.status_code})")
        except Exception as rss_err:
            logger.error(f"RSS 피드 파싱 중 치명적 오류 발생: {rss_err}")
            
        return keywords

    def fetch_autocomplete(self, seed_keywords):
        """구글 자동완성 API를 통한 확장 키워드 수집"""
        keywords = set()
        if not seed_keywords:
            logger.warning("시드 키워드가 없어 자동완성을 진행하지 않습니다.")
            return keywords

        logger.info("구글 자동완성 키워드 수집 중...")
        seeds = list(seed_keywords)[:10]
        
        for seed in seeds:
            try:
                url = f"https://suggestqueries.google.com/client/youtube?client=chrome&hl=ko&gl=kr&q={urllib.parse.quote(seed)}"
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    result = response.json()
                    if len(result) > 1:
                        keywords.update(result[1])
                time.sleep(random.uniform(0.8, 1.5))
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
            kw_clean = " ".join(kw.split()).lower()
            
            if len(kw_clean) < 2 or len(kw_clean) > 30:
                continue
                
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
        """기본 점수에 CPC 보너스와 롱테일 보너스를 조합한 가중치 연산"""
        base_score = random.randint(50, 85)
        
        cpc_bonus = 0.0
        for core_word, bonus in HIGH_CPC_DATABASE.items():
            if core_word in keyword:
                cpc_bonus += bonus * 10
                
        length_bonus = 5 if 5 <= len(keyword) <= 15 else 0
        
        final_score = round(base_score + cpc_bonus + length_bonus, 2)
        return final_score

# ==========================================
# 5. 메인 컨트롤러 파이프라인 (Main)
# ==========================================
def main():
    logger.info("🚀 키워드 갱신 파이프라인 프로세스 시작")
    
    existing_data = []
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
            logger.info(f"기존 저장 파일에서 {len(existing_data)}개의 키워드를 백업용으로 불러왔습니다.")
        except Exception as e:
            logger.error(f"기존 파일 로드 실패: {e}")

    try:
        collector = KeywordCollector()
        
        # 1단계: 트렌드 키워드 수집 (API 실패 시 RSS로 우회됨)
        raw_keywords = collector.fetch_google_trending()
        
        # 2단계: 자동완성 확장 키워드 확보
        extended_keywords = collector.fetch_autocomplete(raw_keywords)
        total_raw = raw_keywords.union(extended_keywords)
        
        # 3단계: 필터링 및 전처리
        filtered_keywords = KeywordFilter.clean_and_validate(total_raw)
        
        # 4단계: 스코어링 연산
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
        
        # 파일 저장 및 안전장치 검증
        if scored_list:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(scored_list, f, ensure_ascii=False, indent=4)
            logger.info(f"🎉 성공! {len(scored_list)}개의 최적화 키워드가 '{DATA_FILE}'에 안정적으로 반영되었습니다.")
        else:
            raise ValueError("모든 수집 및 우회 경로에서 키워드를 확보하지 못했습니다.")
            
    except Exception as e:
        logger.error(f"🚨 파이프라인 실행 중 심각한 예외 발생: {e}")
        logger.info("안전 관리 규칙에 따라 기존 'keywords_queue.json' 데이터 파일 상태가 그대로 보존됩니다.")

if __name__ == "__main__":
    main()
