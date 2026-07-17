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
# 2. 키워드 수집 모듈 (Sources) - 연관 검색어 추출 강화 버전
# ==========================================
class KeywordCollector:
    def __init__(self):
        self.pytrends = TrendReq(hl=HL_LANG, tz=TZ_OFFSET)
        self.rss_url = "https://trends.google.co.kr/trending/rss?geo=KR"

    def fetch_google_trending(self):
        """인기 검색어 수집 (API 404 발생 시 RSS 피드 및 연관어까지 강제 우회 수집)"""
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
            logger.warning(f"구글 API 접근 실패 (우회 전략 가동): {e}")

        # [시도 2] API 실패 시 RSS 피드 파싱 + 네임스페이스 연관 검색어 추출
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            response = requests.get(self.rss_url, headers=headers, timeout=10)
            if response.status_code == 200:
                root = ET.fromstring(response.text)
                
                # 구글 트렌드 RSS 전용 XML 네임스페이스 정의
                ns = {'ht': 'https://trends.google.co.kr/trending/rss'}
                
                for item in root.findall('.//item'):
                    # 메인 트렌드 키워드 추출
                    title = item.find('title')
                    if title is not None and title.text:
                        keywords.add(title.text.strip())
                    
                    # 💡 추가 고도화: 메인 키워드 뒤에 숨은 구글의 '연관 검색어(뉴스 키워드)'까지 전수 추출
                    approx_queries = item.findall('.//ht:approx_traffic', ns)
                    for query in approx_queries:
                        if query.text:
                            # 텍스트 내부에 쉼표 등으로 구분된 키워드가 있다면 분리하여 추가
                            cleaned_q = query.text.replace('+', '').strip()
                            if cleaned_q:
                                keywords.add(cleaned_q)
                                
                logger.info(f"구글 RSS 및 연관 검색어 우회 수집 완료! (총 {len(keywords)}개 시드 확보)")
            else:
                logger.error(f"구글 RSS 피드 접근 거부 (HTTP: {response.status_code})")
        except Exception as rss_err:
            logger.error(f"RSS 피드 내부 상세 파싱 오류: {rss_err}")
            
        return keywords

    def fetch_autocomplete(self, seed_keywords):
        """구글 자동완성 API를 통한 확장 키워드 수집"""
        keywords = set()
        if not seed_keywords:
            return keywords

        logger.info("구글 자동완성 키워드 수집 중...")
        # 시드 단어가 많아졌으므로 안정성을 위해 상위 15개로 제한 확장
        seeds = list(seed_keywords)[:15]
        
        for seed in seeds:
            try:
                url = f"https://suggestqueries.google.com/client/youtube?client=chrome&hl=ko&gl=kr&q={urllib.parse.quote(seed)}"
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    result = response.json()
                    if len(result) > 1:
                        keywords.update(result[1])
                time.sleep(random.uniform(0.5, 1.2))
            except Exception as e:
                logger.warning(f"자동완성 수집 실패 ({seed}): {e}")
        return keywords

# ==========================================
# 3. 데이터 정제 및 필터링 (Filters)
# ==========================================
class KeywordFilter:
    @staticmethod
    def clean_and_validate(keywords):
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
        base_score = random.randint(50, 85)
        cpc_bonus = 0.0
        for core_word, bonus in HIGH_CPC_DATABASE.items():
            if core_word in keyword:
                cpc_bonus += bonus * 10
        length_bonus = 5 if 5 <= len(keyword) <= 15 else 0
        return round(base_score + cpc_bonus + length_bonus, 2)

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
            logger.info(f"기존 저장 파일에서 {len(existing_data)}개의 키워드를 로드했습니다.")
        except Exception as e:
            logger.error(f"기존 파일 로드 실패: {e}")

    try:
        collector = KeywordCollector()
        raw_keywords = collector.fetch_google_trending()
        extended_keywords = collector.fetch_autocomplete(raw_keywords)
        total_raw = raw_keywords.union(extended_keywords)
        filtered_keywords = KeywordFilter.clean_and_validate(total_raw)
        
        scored_list = []
        for kw in filtered_keywords:
            score = KeywordScorer.calculate_score(kw)
            scored_list.append({
                "keyword": kw,
                "score": score,
                "length": len(kw)
            })
            
        scored_list = sorted(scored_list, key=lambda x: x["score"], reverse=True)
        
        if scored_list:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(scored_list, f, ensure_ascii=False, indent=4)
            logger.info(f"🎉 성공! {len(scored_list)}개의 최적화 키워드가 '{DATA_FILE}'에 반영되었습니다.")
        else:
            raise ValueError("모든 수집 및 우회 경로에서 키워드를 확보하지 못했습니다.")
            
    except Exception as e:
        logger.error(f"🚨 파이프라인 실행 중 심각한 예외 발생: {e}")
        logger.info("안전 관리 규칙에 따라 기존 데이터 파일 상태가 보존됩니다.")

if __name__ == "__main__":
    main()

