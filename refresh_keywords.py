# -*- coding: utf-8 -*-
"""
구글 트렌드(대한민국) 일일 인기 검색어 1~7위를 가져와서
keywords_queue.json의 "pending" 목록에 자동으로 채워 넣습니다.

데이터 출처: 구글이 공식 제공하는 트렌드 RSS 피드
  https://trends.google.com/trends/trendingsearches/daily/rss?geo=KR
(별도 API 키 필요 없음, 무료, 스크래핑이 아니라 구글이 직접 제공하는 공식 피드)

동작:
  1. RSS 피드에서 상위 7개 키워드 추출
  2. 이미 완료(completed)됐거나 대기 중(pending)인 키워드는 제외 (중복 방지)
  3. 새 키워드만 pending 목록 뒤에 추가
  4. keywords_queue.json 저장 (실제 git commit/push는 워크플로 파일이 담당)

실행: python refresh_keywords.py
자동화: .github/workflows/refresh_keywords.yml 이 매주 자동 실행합니다.
"""

import json
import os
import xml.etree.ElementTree as ET

import requests

QUEUE_FILE = "keywords_queue.json"
TRENDS_RSS_URL = "https://trends.google.com/trends/trendingsearches/daily/rss?geo=KR"
TOP_N = 7


def fetch_top_trends(n: int = TOP_N) -> list[str]:
    """구글 트렌드 RSS에서 상위 n개 키워드를 가져옵니다."""
    resp = requests.get(TRENDS_RSS_URL, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()

    root = ET.fromstring(resp.content)
    titles = [item.findtext("title") for item in root.iter("item")]
    titles = [t.strip() for t in titles if t and t.strip()]

    return titles[:n]


def load_queue() -> dict:
    if not os.path.exists(QUEUE_FILE):
        return {"pending": [], "completed": []}
    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_queue(queue: dict) -> None:
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)


def run():
    print("[구글 트렌드] 대한민국 일일 인기 검색어 가져오는 중...")
    try:
        trends = fetch_top_trends()
    except Exception as e:
        print(f"[오류] 트렌드 조회 실패: {e}")
        print("네트워크 문제이거나 구글 쪽 피드 형식이 바뀌었을 수 있습니다. 이번 실행은 건너뜁니다.")
        return

    if not trends:
        print("[안내] 가져온 키워드가 없습니다 (피드 응답이 비어있음). 건너뜁니다.")
        return

    print(f"[구글 트렌드] 상위 {len(trends)}개: {trends}")

    queue = load_queue()
    existing = set(queue.get("pending", [])) | set(queue.get("completed", []))

    new_keywords = [t for t in trends if t not in existing]
    skipped = len(trends) - len(new_keywords)

    queue.setdefault("pending", []).extend(new_keywords)
    save_queue(queue)

    print(f"[완료] 새로 추가된 키워드 {len(new_keywords)}개 (중복 제외 {skipped}개)")
    print(f"[완료] 현재 대기 중인 키워드 총 {len(queue['pending'])}개")


if __name__ == "__main__":
    run()
