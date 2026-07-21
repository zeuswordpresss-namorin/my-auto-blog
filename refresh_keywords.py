# -*- coding: utf-8 -*-
"""
구글 트렌드(대한민국) 일일 인기 검색어 1~7위를 가져와서
keywords_queue.json의 "pending" 목록에 자동으로 채워 넣습니다.

동작 방식:
  1. 구글 트렌드 공식 RSS 피드에서 상위 7개 키워드 추출
  2. 이미 완료(completed)되었거나 대기 중(pending)인 키워드는 제외하여 중복 방지
  3. 새 키워드만 pending 목록 뒤에 추가 저장
"""

import json
import os
import sys
import xml.etree.ElementTree as ET
import requests

QUEUE_FILE = "keywords_queue.json"

# 구글 트렌드 RSS 주소 목록 (우선순위 순)
TRENDS_RSS_URLS = [
    "https://trends.google.com/trending/rss?geo=KR",
    "https://trends.google.com/trends/trendingsearches/daily/rss?geo=KR",
]

TOP_N = 7
REQUEST_TIMEOUT = 15  # 초 단위 타임아웃 설정


def fetch_top_trends(n: int = TOP_N) -> list[str]:
    """
    구글 트렌드 RSS 피드에서 상위 n개의 키워드를 안전하게 가져옵니다.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    
    last_error = None

    for url in TRENDS_RSS_URLS:
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT, headers=headers)
            response.raise_for_status()

            # XML 파싱
            root = ET.fromstring(response.content)
            
            # RSS 내 item 태그의 title 추출
            titles = []
            for item in root.iter("item"):
                title_text = item.findtext("title")
                if title_text and title_text.strip():
                    titles.append(title_text.strip())

            if titles:
                print(f"[성공] RSS 수집 완료 (출처: {url})")
                return titles[:n]
            
            last_error = f"{url} - 응답은 성공했으나 추출된 키워드가 없습니다."

        except requests.RequestException as req_err:
            last_error = f"{url} - 네트워크/HTTP 요청 실패: {req_err}"
            print(f"[경고] {last_error}")
        except ET.ParseError as xml_err:
            last_error = f"{url} - XML 파싱 실패: {xml_err}"
            print(f"[경고] {last_error}")
        except Exception as gen_err:
            last_error = f"{url} - 예기치 못한 오류: {gen_err}"
            print(f"[경고] {last_error}")

    raise RuntimeError(f"모든 트렌드 URL에서 수집에 실패했습니다. (마지막 오류: {last_error})")


def load_queue() -> dict:
    """
    기존 큐 파일을 읽어옵니다. 파일이 없거나 유효하지 않으면 기본 구조를 반환합니다.
    """
    if not os.path.exists(QUEUE_FILE):
        return {"pending": [], "completed": []}

    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # 기본 데이터 구조 보장
            data.setdefault("pending", [])
            data.setdefault("completed", [])
            return data
    except (json.JSONDecodeError, IOError) as e:
        print(f"[경고] {QUEUE_FILE} 읽기 실패 ({e}). 새로운 큐 구조로 시작합니다.")
        return {"pending": [], "completed": []}


def save_queue(queue: dict) -> None:
    """
    업데이트된 큐 데이터를 파일에 저장합니다.
    """
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)


def main():
    print("=" * 60)
    print("[구글 트렌드] 대한민국 일일 인기 검색어 수집 시작...")
    
    # 1. 키워드 수집
    trends = fetch_top_trends(TOP_N)
    print(f"[수집 완료] 상위 {len(trends)}개 키워드: {trends}")

    # 2. 기존 큐 로드 및 중복 검사
    queue = load_queue()
    existing_keywords = set(queue.get("pending", [])) | set(queue.get("completed", []))

    new_keywords = [t for t in trends if t not in existing_keywords]
    skipped_count = len(trends) - len(new_keywords)

    # 3. 신규 키워드 추가 및 저장
    queue["pending"].extend(new_keywords)
    save_queue(queue)

    # 4. 결과 출력
    print(f"[처리 완료] 신규 추가된 키워드: {len(new_keywords)}개 (중복 제외됨: {skipped_count}개)")
    print(f"[현재 상태] 대기 중인 전체 키워드: {len(queue['pending'])}개")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"\n[최종 치명적 오류] 실행 실패: {error}")
        sys.exit(1)
