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
# 2. 키워드 수집 모듈 (Sources)
# ==========================================
class KeywordCollector:
    def __init__(self):
        # GitHub Actions 환경에서 404를 유발하는 객체를 배제하고, RSS 트렌드 방식으로 안전하게 수집합니다.
        self.rss_url = "https://trends.google.co.kr/trending/rss?geo=KR"

    def fetch_google_trending(self):
        """인기 검색어 수집 (RSS 피드로 안정적 수집)"""
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
    logger.info("🚀 주간 키워드 자동 보충 파이프라인 시작")
    
    existing_data = []
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
                if not isinstance(existing_data, list):
                    existing_data = []
            logger.info(f"기존 파일에서 {len(existing_data)}개의 대기 키워드를 확인했습니다.")
        except Exception:
            logger.info("기존 큐 파일이 비어있거나 손상되어 새로 생성합니다.")
            existing_data = []

    try:
        collector = KeywordCollector()
        raw_keywords = collector.fetch_google_trending()
        extended_keywords = collector.fetch_autocomplete(raw_keywords)
        
        # 모든 수집 키워드 결합 후 필터링
        total_raw = raw_keywords.union(extended_keywords)
        filtered_keywords = KeywordFilter.clean_and_validate(total_raw)
        
        # 점수 계산 및 정렬
        scored_list = []
        for kw in filtered_keywords:
            score = KeywordScorer.calculate_score(kw)
            scored_list.append({
                "keyword": kw,
                "score": score,
                "length": len(kw)
            })
            
        # 고점수 순으로 정렬
        scored_list = sorted(scored_list, key=lambda x: x["score"], reverse=True)
        
        # 🌟 워크플로우 목적에 맞게 최상위 핵심 키워드 7개만 추출
        top_7_keywords = scored_list[:7]
        
        if top_7_keywords:
            # 기존 대기열 뒤에 추가하는 방식이 아니라 주간 새로고침(Refresh) 개념이므로 새로 덮어씁니다.
            # (만약 누적을 원하시면 top_7_keywords + existing_data 형태로 구성할 수 있습니다.)
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(top_7_keywords, f, ensure_ascii=False, indent=4)
            
            logger.info("🎯 주간 상위 키워드 7개 추출 완료:")
            for idx, item in enumerate(top_7_keywords, 1):
                logger.info(f"  {idx}위: {item['keyword']} (점수: {item['score']})")
                
            logger.info(f"🎉 성공! {len(top_7_keywords)}개의 최적화 키워드가 '{DATA_FILE}'에 반영되었습니다.")
        else:
            logger.info("수집 및 필터링된 신규 키워드가 없어 기존 파일을 유지합니다.")
            
    except Exception as e:
        logger.info(f"파이프라인 제어 흐름 알림: {e}")

if __name__ == "__main__":
    main()

