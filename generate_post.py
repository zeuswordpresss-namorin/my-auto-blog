# -*- coding: utf-8 -*-
"""
GitHub Actions 위에서 실행되는 자동 블로그 파이프라인 스크립트 (v3 - 업그레이드판)

v2에서 추가된 것:
  1. 쿠팡 마크업(제휴) 링크 실전 업그레이드
     - 쿠팡파트너스 Open API(HMAC 서명) 딥링크 발급 시도
     - API 키 미설정/실패 시 기존 태그 방식 검색 링크로 자동 대체 (항상 동작 보장)
  2. 상위노출(SEO) 강화
     - Open Graph / Twitter Card 메타태그, canonical URL
     - sitemap.xml / robots.txt 매 실행마다 자동 갱신
  3. 수익화 피드백 관리
     - Google Analytics 4(GA4) 추적 코드 삽입 (측정 ID 설정 시)
     - docs/dashboard.html : 지금까지 발행된 글 + 확인 링크 모음 (폰에서 보는 성과 관리 화면)

v3에서 추가된 것:
  4. AI 스키마 마크업 자동 선택
     - Gemini가 글 내용을 보고 FAQPage / HowTo / Article 중 구글 상위노출에
       가장 유리한 구조화 데이터 타입을 스스로 골라 JSON-LD로 생성 (수동 선택 불필요)
  5. 구글 애드센스 자동광고 연동 (전면/앵커 광고 포함)
     - ADSENSE_CLIENT_ID 설정 시 자동광고 스크립트 삽입, 실제 광고 형식/노출 빈도는
       애드센스 사이트의 "자동 광고" 메뉴에서 On/Off
  6. 대시보드에 애드센스 수익 확인 카드 추가

v4에서 추가된 것 (저장소 통합):
  7. 구글 블로거(Blogger) 동시 발행
     - 같은 글/썸네일/스키마 마크업을 GitHub Pages뿐 아니라 Blogger 블로그에도 자동 발행
     - OAuth 리프레시 토큰 방식이라 최초 1회만 인증하면 이후 자동 갱신됨
     - Blogger 관련 Secrets 미설정 시 이 단계는 조용히 건너뛰고 GitHub Pages 발행은 그대로 진행
       (별도의 "Blogger" 저장소/워크플로는 더 이상 필요 없음, 이 저장소 하나로 통합)
"""

import base64
import hashlib
import hmac
import io
import json
import os
import random
import re
import sys
import textwrap
import time
import urllib.parse
from datetime import datetime

import requests
from PIL import Image, ImageDraw, ImageFont

# =====================================================================
# 환경변수로 받는 설정값 (GitHub 저장소 Secrets / Variables에서 자동 주입됨)
# =====================================================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
SITE_TITLE = os.environ.get("SITE_TITLE", "내 자동 블로그")
SITE_TAGLINE = os.environ.get("SITE_TAGLINE", "매일 자동으로 업데이트되는 정보 큐레이션 블로그")
SITE_URL = os.environ.get("SITE_URL", "").rstrip("/")  # 예: https://아이디.github.io/my-auto-blog
GA_MEASUREMENT_ID = os.environ.get("GA_MEASUREMENT_ID", "")  # 예: G-XXXXXXXXXX
GOOGLE_SITE_VERIFICATION = os.environ.get("GOOGLE_SITE_VERIFICATION", "")  # 서치콘솔 HTML 태그 인증용 코드
ADSENSE_CLIENT_ID = os.environ.get("ADSENSE_CLIENT_ID", "")  # 예: ca-pub-1234567890123456
ADSENSE_SLOT_ID = os.environ.get("ADSENSE_SLOT_ID", "")  # 애드센스에서 만든 "디스플레이 광고" 단위 ID (수동 배치용)

COUPANG_PARTNER_TAG = os.environ.get("COUPANG_PARTNER_TAG", "")
COUPANG_ACCESS_KEY = os.environ.get("COUPANG_ACCESS_KEY", "")
COUPANG_SECRET_KEY = os.environ.get("COUPANG_SECRET_KEY", "")

# 구글 블로거 동시발행용 (최초 1회 OAuth 인증 후 자동 갱신되는 리프레시 토큰 방식)
BLOGGER_BLOG_ID = os.environ.get("BLOGGER_BLOG_ID", "")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REFRESH_TOKEN = os.environ.get("GOOGLE_REFRESH_TOKEN", "")

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "font.ttf",
]

DOCS_DIR = "docs"
POSTS_DIR = os.path.join(DOCS_DIR, "posts")
POSTS_JSON = os.path.join(DOCS_DIR, "posts.json")
QUEUE_FILE = "keywords_queue.json"

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash:generateContent?key={api_key}"
)

SYSTEM_PROMPT = """당신은 한국어 SEO 블로그 콘텐츠 작가 겸 구조화 데이터(스키마 마크업) 전문가입니다.
아래 규칙을 지켜 작성하세요:
1. 제목은 검색 의도를 반영하되 과장/낚시성 표현은 피한다. 가능하면 "무직자 비상금 대출 조건 서류"처럼
   3~4개 단어가 조합된 구체적인 롱테일 키워드형 제목을 쓴다 (단, 입력받은 키워드의 의미를 벗어나지 않는다).
   제목은 25~40자 내외로, 구글 검색결과에서 잘리지 않게 한다.
1-1. meta_description은 검색결과 스니펫에 노출되는 요약문이다. 핵심 키워드를 앞부분에 배치하고,
   클릭을 유도하는 문장으로 100~140자 내외로 작성한다 (너무 짧거나 500자를 넘지 않게 한다).
2. 소제목(H2)을 4~6개 사용해 구조화한다.
3. 확인되지 않은 구체적 수치·통계·자격요건·금리·지원금액을 지어내지 않는다. 모르면 "기관별로 다를 수 있다" 식으로
   일반화해서 쓰고, 절대 구체적 숫자를 추측해서 채우지 않는다.
4. 글자 수는 1500~2200자 내외.
5. 두괄식으로 쓴다: 첫 문단(도입부)에서 이 글이 다루는 핵심 답/결론을 먼저 요약 제시하고, 이후 문단에서 자세히 설명한다.
6. 가독성을 위해 본문 중 최소 1곳에 <table> (비교/정리표) 또는 <ul>/<ol> 목록을 반드시 포함한다.
7. 자연스러운 위치에 제품/서비스 추천 문맥을 1곳 만든다 (실제 링크는 넣지 않음, 나중에 자동 삽입됨).
8. 콘텐츠 내용을 보고 아래 3가지 중 구글 상위노출에 가장 유리한 스키마 타입을 스스로 판단해서 고른다:
   - "FAQPage": 자주 묻는 질문/답변 형태로 정리하기 좋은 주제일 때 (예: "~란?", "~ 방법", "~ 차이" 등 질의응답형 검색의도)
   - "HowTo": 순서가 있는 절차/방법을 안내하는 주제일 때 (예: "~하는 법", "~ 설치 방법")
   - "Article": 위 둘에 해당하지 않는 일반 정보/추천/리뷰형 글일 때
9. 고른 스키마 타입에 맞는 데이터를 함께 채운다:
   - FAQPage를 골랐다면 "faq_items"에 실제 본문 내용과 일치하는 질문/답변 3~5개를 넣는다 (본문에도 자연스럽게 Q&A 형태로 녹여쓴다)
   - HowTo를 골랐다면 "howto_steps"에 실제 본문 순서와 일치하는 단계 3~6개를 넣는다 (각 step은 name(단계 제목)과 text(설명))
   - Article이면 faq_items, howto_steps는 빈 배열로 둔다
10. 제목/키워드를 보고 아래 카테고리 중 가장 알맞은 것 하나를 "category"에 고른다 (디자인 테마 자동 매칭용):
    ["뷰티패션", "푸드맛집", "여행", "테크IT", "재테크머니", "헬스운동", "홈인테리어", "대출보험", "정부지원금", "라이프스타일"]
    애매하면 "라이프스타일"을 선택한다.
11. category가 "대출보험" 또는 "정부지원금"이면 (실제 금융/정책 정보라 신중해야 하므로):
    - 특정 금융사·상품명을 단정적으로 추천하지 않는다 (일반적인 조건/절차 위주로 설명)
    - 신청 절차나 자격요건은 "일반적으로"라는 표현을 쓰고, 최신 여부는 공식 기관 확인이 필요하다는 점을 본문에 자연스럽게 언급한다
12. 출력은 반드시 아래 JSON 형식만 반환한다. 다른 설명, 코드블록 기호(```) 없이 순수 JSON만 출력한다:
{
  "title": "...",
  "html_body": "...",
  "meta_description": "...",
  "schema_type": "Article 또는 FAQPage 또는 HowTo",
  "faq_items": [{"question": "...", "answer": "..."}],
  "howto_steps": [{"name": "...", "text": "..."}],
  "category": "위 10개 중 하나"
}
html_body는 <h2>, <p>, <table>, <ul> 등을 사용한 HTML 조각이어야 한다."""


# =====================================================================
# 카테고리별 트렌디 테마 - 글 주제(category)에 맞춰 자동으로 색상/폰트/뱃지가 바뀝니다
# =====================================================================
CATEGORY_THEMES = {
    "뷰티패션": {
        "gradient": [(255, 107, 157), (255, 154, 158), (250, 208, 196)],
        "accent": "#ff6b9d",
        "badge": "💄 뷰티·패션",
        "label": "BEAUTY",
        "font": "Gowun+Dodum",
        "decor": ["💄", "💅", "👗", "👠", "💋", "🎀", "💎", "🌸"],
    },
    "푸드맛집": {
        "gradient": [(255, 107, 53), (247, 147, 30), (255, 210, 63)],
        "accent": "#ff6b35",
        "badge": "🍽️ 푸드·맛집",
        "label": "FOOD",
        "font": "Jua",
        "decor": ["🍕", "🍔", "🍰", "🍜", "🍩", "☕", "🍓", "🧁"],
    },
    "여행": {
        "gradient": [(17, 153, 142), (56, 239, 125), (100, 210, 255)],
        "accent": "#11998e",
        "badge": "✈️ 여행",
        "label": "TRAVEL",
        "font": "Gowun+Dodum",
        "decor": ["✈️", "🌴", "🗺️", "🧳", "🏖️", "📸", "🚗", "🗼"],
    },
    "테크IT": {
        "gradient": [(30, 60, 114), (42, 82, 152), (0, 198, 255)],
        "accent": "#2a5298",
        "badge": "💻 테크·IT",
        "label": "TECH",
        "font": "Noto+Sans+KR:wght@700",
        "decor": ["💻", "⌨️", "🖥️", "📱", "🔌", "🤖", "⚡", "🛰️"],
    },
    "재테크머니": {
        "gradient": [(17, 105, 79), (56, 173, 118), (168, 224, 99)],
        "accent": "#11694f",
        "badge": "💰 재테크",
        "label": "MONEY",
        "font": "Noto+Sans+KR:wght@700",
        "decor": ["💰", "💵", "📈", "🪙", "🏦", "💳", "📊", "🐷"],
    },
    "헬스운동": {
        "gradient": [(19, 78, 94), (113, 178, 128), (168, 224, 99)],
        "accent": "#134e5e",
        "badge": "💪 헬스·운동",
        "label": "FITNESS",
        "font": "Jua",
        "decor": ["💪", "🏋️", "🥗", "🧘", "🏃", "⏱️", "🚴", "🥑"],
    },
    "홈인테리어": {
        "gradient": [(196, 132, 88), (218, 170, 122), (238, 210, 175)],
        "accent": "#c48458",
        "badge": "🏠 홈·인테리어",
        "label": "HOME",
        "font": "Gowun+Dodum",
        "decor": ["🏠", "🪴", "🕯️", "🛋️", "🖼️", "🧺", "🪞", "🛏️"],
    },
    "라이프스타일": {
        "gradient": [(66, 133, 244), (156, 39, 176), (234, 67, 121)],
        "accent": "#4a90d9",
        "badge": "✨ 라이프스타일",
        "label": "LIFESTYLE",
        "font": "Noto+Sans+KR:wght@700",
        "decor": ["✨", "🌸", "☕", "📓", "🎧", "🕊️", "🌿", "⭐"],
    },
    "대출보험": {
        "gradient": [(20, 30, 48), (36, 59, 85), (65, 90, 119)],
        "accent": "#1e3a5f",
        "badge": "🏦 대출·보험",
        "label": "FINANCE",
        "font": "Noto+Sans+KR:wght@700",
        "decor": ["🏦", "📄", "💳", "🔍", "📞", "✅", "💼", "🧾"],
        "ymyl": True,
    },
    "정부지원금": {
        "gradient": [(0, 91, 82), (0, 128, 105), (82, 183, 136)],
        "accent": "#00695c",
        "badge": "🏛️ 정부지원금",
        "label": "SUPPORT",
        "font": "Noto+Sans+KR:wght@700",
        "decor": ["🏛️", "📋", "🖊️", "📅", "✅", "💌", "🪪", "📢"],
        "ymyl": True,
    },
}
DEFAULT_THEME = CATEGORY_THEMES["라이프스타일"]


def get_theme(category: str) -> dict:
    return CATEGORY_THEMES.get(category, DEFAULT_THEME)


# 카테고리별 무료 일러스트 생성 프롬프트 (Pollinations.ai - 무료, API 키 불필요)
ILLUSTRATION_PROMPTS = {
    "뷰티패션": "flat vector illustration of cosmetics lipstick and fashion clothing items, minimal pastel style",
    "푸드맛집": "flat vector illustration of food dishes and cafe coffee items, minimal pastel style",
    "여행": "flat vector illustration of travel landscape airplane suitcase palm tree, minimal pastel style",
    "테크IT": "flat vector illustration of laptop computer and technology icons, minimal modern style",
    "재테크머니": "flat vector illustration of coins money and finance growth chart, minimal pastel style",
    "헬스운동": "flat vector illustration of fitness workout dumbbell and healthy food, minimal pastel style",
    "홈인테리어": "flat vector illustration of cozy home interior furniture and plants, minimal pastel style",
    "대출보험": "flat vector illustration of bank building document and contract, minimal professional style",
    "정부지원금": "flat vector illustration of government building document and checklist, minimal clean style",
    "라이프스타일": "flat vector illustration of coffee book and cozy lifestyle items, minimal pastel style",
}
ILLUSTRATION_SUFFIX = ", simple shapes, no text, no watermark, white background, isolated icons"


def build_decor_html(theme: dict, seed: str) -> str:
    """글 주제에 맞는 아기자기한 이모지 일러스트를 배경 빈 공간에 랜덤 배치합니다.
    seed(글 slug)로 고정해서 같은 글은 새로고침해도 항상 같은 배치가 나옵니다."""
    rng = random.Random(seed)
    emojis = theme["decor"]
    count = rng.randint(9, 12)
    items = []
    for _ in range(count):
        emoji = rng.choice(emojis)
        top = rng.randint(0, 96)
        left = rng.randint(0, 92)
        size = rng.randint(26, 58)
        rotate = rng.randint(-30, 30)
        opacity = round(rng.uniform(0.07, 0.16), 2)
        items.append(
            f'<span class="decor-item" style="top:{top}%;left:{left}%;font-size:{size}px;'
            f'opacity:{opacity};transform:rotate({rotate}deg);">{emoji}</span>'
        )
    return '<div class="decor-layer" aria-hidden="true">' + "".join(items) + "</div>"


def _search_console_meta() -> str:
    if not GOOGLE_SITE_VERIFICATION:
        return ""
    return f'\n<meta name="google-site-verification" content="{GOOGLE_SITE_VERIFICATION}">'


def _ga_snippet() -> str:
    if not GA_MEASUREMENT_ID:
        return ""
    return f"""
<script async src="https://www.googletagmanager.com/gtag/js?id={GA_MEASUREMENT_ID}"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', '{GA_MEASUREMENT_ID}');
</script>"""


def _adsense_snippet() -> str:
    """구글 애드센스 자동광고 스크립트. 이 한 줄만 있으면 배너/전면(interstitial)/앵커 광고를
    구글이 페이지 내용에 맞게 자동으로 배치합니다 (실제 On/Off 및 광고 형식 세부설정은
    애드센스 사이트의 '자동 광고' 메뉴에서 합니다)."""
    if not ADSENSE_CLIENT_ID:
        return ""
    return (
        f'\n<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js'
        f'?client={ADSENSE_CLIENT_ID}" crossorigin="anonymous"></script>'
    )


def build_json_ld(article: dict, canonical_url: str, thumb_url: str, date: str, platform: str = "github") -> str:
    """AI가 고른 스키마 타입(schema_type)에 맞춰 JSON-LD 구조화 데이터를 만듭니다.
    platform="blogger"면 일반 Article 대신 BlogPosting 타입을 사용합니다 (블로그 플랫폼 권장 스키마)."""
    schema_type = article.get("schema_type", "Article")
    title = article["title"]
    meta_description = article.get("meta_description", "")
    article_type = "BlogPosting" if platform == "blogger" else "Article"

    if schema_type == "FAQPage" and article.get("faq_items"):
        data = {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": qa.get("question", ""),
                    "acceptedAnswer": {"@type": "Answer", "text": qa.get("answer", "")},
                }
                for qa in article["faq_items"]
            ],
        }
    elif schema_type == "HowTo" and article.get("howto_steps"):
        data = {
            "@context": "https://schema.org",
            "@type": "HowTo",
            "name": title,
            "description": meta_description,
            "step": [
                {"@type": "HowToStep", "name": s.get("name", ""), "text": s.get("text", "")}
                for s in article["howto_steps"]
            ],
        }
    else:
        schema_type = article_type
        data = {
            "@context": "https://schema.org",
            "@type": article_type,
            "headline": title,
            "description": meta_description,
            "image": thumb_url,
            "datePublished": date,
            "author": {"@type": "Organization", "name": SITE_TITLE},
        }

    data.pop("@context", None)
    breadcrumb = {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": SITE_TITLE, "item": (SITE_URL + "/") if SITE_URL else "../index.html"},
            {"@type": "ListItem", "position": 2, "name": article.get("category", "라이프스타일"), "item": (SITE_URL + "/") if SITE_URL else "../index.html"},
            {"@type": "ListItem", "position": 3, "name": title, "item": canonical_url},
        ],
    }
    graph_data = {"@context": "https://schema.org", "@graph": [data, breadcrumb]}

    print(f"  → [스키마 마크업] AI가 선택한 타입: {schema_type} (+ BreadcrumbList)")
    return json.dumps(graph_data, ensure_ascii=False, indent=2)


def build_blog_index_json_ld(posts: list) -> str:
    """홈 화면용 Blog 스키마 마크업 - 최근 글 목록을 구조화 데이터로 노출합니다."""
    data = {
        "@context": "https://schema.org",
        "@type": "Blog",
        "name": SITE_TITLE,
        "url": (SITE_URL + "/") if SITE_URL else ".",
        "blogPost": [
            {
                "@type": "BlogPosting",
                "headline": p["title"],
                "url": (f"{SITE_URL}/{p['file']}" if SITE_URL else p["file"]),
                "datePublished": p["date"],
                "image": (f"{SITE_URL}/{p['thumb']}" if SITE_URL else p["thumb"]),
            }
            for p in posts[:10]
        ],
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


POST_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<meta name="description" content="{meta_description}">
<link rel="canonical" href="{canonical_url}">
<link rel="icon" type="image/png" href="../favicon.png">{search_console_meta}
<meta property="og:type" content="article">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{meta_description}">
<meta property="og:image" content="{thumb_url}">
<meta property="og:url" content="{canonical_url}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{meta_description}">
<meta name="twitter:image" content="{thumb_url}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family={font}&family=Noto+Sans+KR:wght@400;700&display=swap" rel="stylesheet">
<script type="application/ld+json">
{json_ld}
</script>{ga_snippet}{adsense_snippet}
<style>
  * {{ box-sizing: border-box; }}
  body {{ position: relative; max-width: 720px; margin: 0 auto; padding: 0 20px 60px; font-family: 'Noto Sans KR', -apple-system, sans-serif; line-height: 1.75; color: #1a1a1a; background: #fafafa; overflow-x: hidden; }}
  .decor-layer {{ position: absolute; inset: 0; overflow: hidden; pointer-events: none; z-index: 0; }}
  .decor-item {{ position: absolute; filter: grayscale(0%); user-select: none; }}
  .content {{ position: relative; z-index: 1; }}
  .hero {{ margin: 0 -20px 24px; position: relative; }}
  .hero img {{ width: 100%; aspect-ratio: 16/9; object-fit: cover; display: block; }}
  .badge {{ display: inline-block; background: {accent}; color: #fff; font-size: 0.8em; font-weight: 700; padding: 5px 14px; border-radius: 999px; margin: 20px 0 10px; }}
  h1 {{ font-family: '{font_family}', 'Noto Sans KR', sans-serif; font-size: 1.9em; line-height: 1.35; margin: 0 0 8px; }}
  h2 {{ font-family: '{font_family}', 'Noto Sans KR', sans-serif; font-size: 1.35em; margin-top: 2em; padding: 10px 14px; background: linear-gradient(90deg, {accent}22, transparent); border-left: 5px solid {accent}; border-radius: 4px; position: relative; z-index: 1; }}
  p {{ margin: 1em 0; position: relative; z-index: 1; }}
  a.back {{ display: inline-block; margin: 20px 0; color: {accent}; text-decoration: none; font-weight: 700; position: relative; z-index: 1; }}
  .meta {{ color: #999; font-size: 0.85em; margin-bottom: 4px; }}
  .related {{ margin-top: 60px; padding-top: 24px; border-top: 2px solid #eee; }}
  .related h3 {{ font-size: 1.1em; margin-bottom: 14px; }}
  .related-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
  .related-card {{ text-decoration: none; color: #1a1a1a; }}
  .related-card img {{ width: 100%; aspect-ratio: 16/9; object-fit: cover; border-radius: 10px; margin-bottom: 6px; }}
  .related-card span {{ font-size: 0.88em; font-weight: 500; }}
</style>
</head>
<body>
{decor_html}
<div class="content">
<a class="back" href="../index.html">← 목록으로</a>
<div class="hero"><img src="../thumbs/{thumb_filename}" alt="{title}" loading="eager" fetchpriority="high"></div>
<span class="badge">{badge}</span>
<h1>{title}</h1>
<p class="meta">{date}</p>
{html_body}
{related_html}
{bottom_ad}
</div>
</body>
</html>
"""

ALL_THEME_FONTS = sorted({t["font"] for t in CATEGORY_THEMES.values()})


def _google_fonts_url() -> str:
    families = "&family=".join(ALL_THEME_FONTS)
    return f"https://fonts.googleapis.com/css2?family={families}&family=Noto+Sans+KR:wght@400;700;900&display=swap"


INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{site_title}</title>
<meta name="description" content="{site_title} - 자동으로 업데이트되는 블로그">
<link rel="canonical" href="{site_url}/">
<link rel="icon" type="image/png" href="favicon.png">{search_console_meta}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="{fonts_url}" rel="stylesheet">
<script type="application/ld+json">
{blog_json_ld}
</script>{ga_snippet}{adsense_snippet}
<style>
  * {{ box-sizing: border-box; }}
  body {{ max-width: 1000px; margin: 0 auto; padding: 0 0 60px; font-family: 'Noto Sans KR', -apple-system, sans-serif; background:#f5f5f7; color:#1a1a1a; }}
  .masthead {{ position: relative; margin-bottom: 26px; }}
  .masthead img {{ width: 100%; aspect-ratio: 1600/420; object-fit: cover; display:block; }}
  .masthead-inner {{ padding: 0 20px; }}
  .brand-row {{ display:flex; align-items:center; gap:12px; margin: 18px 0 4px; }}
  .brand-row img.logo {{ width:44px; height:44px; border-radius:50%; box-shadow: 0 2px 8px rgba(0,0,0,0.15); }}
  h1.site-title {{ font-family: 'Jua', sans-serif; font-size: 1.6em; margin:0; }}
  .dash-link {{ margin-left:auto; font-size: 0.45em; color:#888; text-decoration:none; background:#eee; padding:6px 14px; border-radius:999px; }}
  .intro {{ color:#555; font-size:0.95em; margin: 4px 0 16px; line-height:1.6; }}
  .pill-row {{ display:flex; flex-wrap:wrap; gap:8px; margin-bottom: 10px; }}
  .pill {{ font-size:0.78em; font-weight:700; color:#fff; padding:5px 13px; border-radius:999px; }}
  .content-wrap {{ padding: 0 20px; }}
  .tier-label {{ font-size: 0.85em; font-weight:900; color:#aaa; letter-spacing:2px; margin: 34px 0 12px; text-transform:uppercase; }}
  .tier-label:first-of-type {{ margin-top: 10px; }}

  /* 상단(TOP) - 히어로 1건, 가장 큰 임팩트 */
  .hero {{ display:block; text-decoration:none; color:#1a1a1a; background:#fff; border-radius:20px; overflow:hidden; box-shadow: 0 6px 24px rgba(0,0,0,0.10); }}
  .hero img {{ width:100%; aspect-ratio: 21/9; object-fit:cover; display:block; }}
  .hero-body {{ padding: 22px 26px 28px; }}
  .hero-badge {{ display:inline-block; font-size:0.8em; font-weight:700; color:#fff; padding:5px 14px; border-radius:999px; margin-bottom:12px; }}
  .hero-title {{ font-size: 1.7em; font-weight:800; line-height:1.35; }}

  /* 중단(MID) - 2단 그리드, 중간 크기 */
  .mid-grid {{ display:grid; grid-template-columns: 1fr 1fr; gap:18px; }}
  .mid-card {{ text-decoration:none; color:#1a1a1a; background:#fff; border-radius:16px; overflow:hidden; box-shadow: 0 3px 14px rgba(0,0,0,0.08); transition: transform .15s ease; }}
  .mid-card:hover {{ transform: translateY(-3px); }}
  .mid-card img {{ width:100%; aspect-ratio:16/9; object-fit:cover; display:block; }}
  .mid-body {{ padding: 14px 16px 18px; }}
  .mid-title {{ font-weight:700; font-size:1.08em; line-height:1.4; }}

  /* 하단(BOTTOM) - 촘촘한 아카이브 그리드, 작은 크기 */
  .bottom-grid {{ display:grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap:14px; }}
  .bottom-card {{ text-decoration:none; color:#1a1a1a; background:#fff; border-radius:10px; overflow:hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
  .bottom-card img {{ width:100%; aspect-ratio:16/10; object-fit:cover; display:block; }}
  .bottom-body {{ padding: 8px 10px 12px; }}
  .bottom-title {{ font-weight:600; font-size:0.85em; line-height:1.35; }}

  .badge-sm {{ display:inline-block; font-size:0.65em; font-weight:700; color:#fff; padding:2px 8px; border-radius:999px; margin-bottom:5px; }}
  .date {{ color: #999; font-size: 0.78em; margin-top: 5px; }}
  .site-footer {{ margin-top: 50px; padding: 24px 20px; border-top: 1px solid #e2e2e2; text-align:center; color:#999; font-size:0.82em; }}
  .site-footer a {{ color:#777; text-decoration:none; margin: 0 8px; }}
  .site-footer a:hover {{ color:#b45309; }}
</style>
</head>
<body>
<div class="masthead">
  <img src="banner.webp" alt="{site_title}" loading="eager" fetchpriority="high">
</div>
<div class="masthead-inner">
  <div class="brand-row">
    <img class="logo" src="logo.webp" alt="{site_title} 로고">
    <h1 class="site-title">{site_title}</h1>
    <a class="dash-link" href="dashboard.html">📊 성과관리</a>
  </div>
  <p class="intro">{site_tagline}</p>
  <div class="pill-row">{category_pills}</div>
</div>

<div class="content-wrap">
{hero_html}
{mid_html}
{bottom_html}
</div>
{footer_html}
</body>
</html>
"""

DASHBOARD_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>성과 관리 - {site_title}</title>
<style>
  body {{ max-width: 760px; margin: 40px auto; padding: 0 20px; font-family: -apple-system, sans-serif; color:#222; }}
  h1 {{ font-size: 1.5em; }}
  h2 {{ font-size: 1.1em; margin-top: 2em; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.9em; }}
  th, td {{ text-align: left; padding: 8px 4px; border-bottom: 1px solid #eee; }}
  a {{ color: #4a90d9; }}
  .card {{ background:#f7f7f9; border-radius:8px; padding:16px; margin: 10px 0; }}
  a.back {{ display: inline-block; margin-bottom: 20px; color: #4a90d9; text-decoration: none; }}
</style>
</head>
<body>
<a class="back" href="index.html">← 블로그로</a>
<h1>📊 성과 관리 대시보드</h1>

<div class="card">
  <b>실시간 트래픽 확인 (GA4)</b><br>
  플레이스토어 "Google Analytics" 앱 설치 후 이 사이트의 방문자/인기글을 확인하세요.<br>
  <a href="https://analytics.google.com" target="_blank">analytics.google.com 바로가기</a>
</div>

<div class="card">
  <b>수익(쿠팡 마크업 수수료) 확인</b><br>
  쿠팡파트너스 앱 또는 사이트에서 클릭수/수익을 확인하세요.<br>
  <a href="https://partners.coupang.com" target="_blank">partners.coupang.com 바로가기</a>
</div>

<div class="card">
  <b>광고 수익(애드센스) 확인</b><br>
  플레이스토어 "Google AdSense" 앱 설치 후 페이지뷰/광고 수익(전면광고 포함)을 확인하세요.<br>
  <a href="https://www.google.com/adsense" target="_blank">adsense.google.com 바로가기</a>
</div>

<div class="card">
  <b>검색 노출 확인 (Google Search Console)</b><br>
  사이트가 구글 검색에 얼마나 노출/클릭되는지 확인하세요. 최초 1회 소유권 인증이 필요합니다.<br>
  <a href="https://search.google.com/search-console" target="_blank">search.google.com/search-console 바로가기</a>
</div>

<h2>발행된 글 목록 ({post_count}개)</h2>
<table>
<tr><th>날짜</th><th>제목</th><th>바로가기</th></tr>
{rows}
</table>
</body>
</html>
"""

SITEMAP_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>{site_url}/</loc></url>
{url_entries}
</urlset>
"""

ROBOTS_TXT = """User-agent: *
Allow: /

Sitemap: {site_url}/sitemap.xml
"""

GEMINI_GRADIENT_COLORS = [(66, 133, 244), (156, 39, 176), (234, 67, 121)]
THUMB_SIZE = (1280, 720)


def slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text).strip()
    return re.sub(r"[\s]+", "-", text) or "post"


def get_title_from_args_or_queue() -> str:
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return sys.argv[1].strip()

    if not os.path.exists(QUEUE_FILE):
        raise RuntimeError(f"{QUEUE_FILE} 이 없습니다. 저장소 루트에 큐 파일을 만들어주세요.")

    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
        queue = json.load(f)

    pending = queue.get("pending", [])
    if not pending:
        raise RuntimeError("대기 중인 키워드가 없습니다. keywords_queue.json의 pending 목록을 채워주세요.")

    title = pending.pop(0)
    queue.setdefault("completed", []).append(title)
    queue["pending"] = pending

    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)

    return title


def generate_article(title: str) -> dict:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY 환경변수가 비어있습니다. 저장소 Secrets 설정을 확인하세요.")

    url = GEMINI_URL.format(api_key=GEMINI_API_KEY)
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": f"제목: '{title}' 에 대한 블로그 글을 작성해주세요."}]}],
    }

    last_error = None
    for attempt in range(1, 4):
        try:
            resp = requests.post(url, json=payload, timeout=60)
            if resp.status_code in (429, 503):
                wait = 15 * attempt
                print(f"  → 일시적 오류({resp.status_code}), {wait}초 대기 후 재시도 ({attempt}/3)")
                time.sleep(wait)
                last_error = f"{resp.status_code} 오류 반복됨"
                continue
            resp.raise_for_status()
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            # Gemini가 JSON 뒤에 불필요한 텍스트를 덧붙이는 경우(Extra data 오류) 대비:
            # 첫 번째로 완결되는 JSON 객체만 읽고 나머지는 무시한다.
            decoder = json.JSONDecoder()
            article, _ = decoder.raw_decode(cleaned)
            article["keyword"] = title

            # meta_description 길이 안전장치 (검색결과 스니펫 잘림/과다 방지)
            desc = article.get("meta_description", "").strip()
            if len(desc) > 160:
                desc = desc[:157].rstrip() + "..."
            article["meta_description"] = desc

            return article
        except (KeyError, IndexError) as e:
            raise ValueError(f"Gemini 응답 형식이 예상과 다릅니다: {e}")
        except json.JSONDecodeError as e:
            raise ValueError(f"AI 응답을 JSON으로 해석하지 못했습니다: {e}")
        except requests.exceptions.RequestException as e:
            last_error = str(e)
            time.sleep(10)

    raise RuntimeError(f"3번 시도했지만 계속 실패했습니다: {last_error}")


def _load_font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    print("[안내] 한글 폰트를 찾지 못해 기본 폰트로 대체합니다 (한글이 깨져 보일 수 있음).")
    return ImageFont.load_default()


def _make_gradient_background(size, colors):
    w, h = size
    base = Image.new("RGB", size, colors[0])
    top = Image.new("RGB", size, colors[-1])
    mask = Image.new("L", size)
    mask.putdata([int(((x / w + y / h) / 2) * 255) for y in range(h) for x in range(w)])
    blended = Image.composite(top, base, mask)

    mid = Image.new("RGB", size, colors[1])
    mid_mask = Image.new("L", size)
    mid_mask.putdata([int(80 * (1 - abs((x / w + y / h) / 2 - 0.5) * 2)) for y in range(h) for x in range(w)])
    return Image.composite(mid, blended, mid_mask)


def _hex_to_rgb(hex_color: str):
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def _fetch_illustration(category: str, size: tuple, seed: int):
    """Pollinations.ai(무료, 키 불필요)에서 카테고리에 맞는 일러스트를 받아옵니다.
    네트워크 실패/타임아웃 등 어떤 이유로든 실패하면 None을 반환하고,
    호출부에서는 그냥 일러스트 없이(그라데이션만으로) 계속 진행합니다."""
    prompt = ILLUSTRATION_PROMPTS.get(category, ILLUSTRATION_PROMPTS["라이프스타일"]) + ILLUSTRATION_SUFFIX
    url = (
        f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}"
        f"?width={size[0]}&height={size[1]}&seed={seed}&nologo=true"
    )
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
        if img.size != size:
            img = img.resize(size)
        return img
    except Exception as e:
        print(f"  → [일러스트] 생성 실패, 그라데이션만 사용: {e}")
        return None


def generate_thumbnail(title: str, output_path: str, theme: dict, category: str = "라이프스타일") -> None:
    img = _make_gradient_background(THUMB_SIZE, theme["gradient"]).convert("RGBA")

    # --- 주제 관련 무료 일러스트를 반투명 배경으로 합성 ---
    seed = int(hashlib.md5(title.encode("utf-8")).hexdigest(), 16) % 100000
    illustration = _fetch_illustration(category, THUMB_SIZE, seed)
    if illustration is not None:
        img = Image.blend(img, illustration, alpha=0.38)

    draw = ImageDraw.Draw(img)
    accent_rgb = _hex_to_rgb(theme["accent"])

    # --- 주제 명시 라벨 뱃지 (좌상단, 카테고리별 포인트컬러로 강한 임팩트) ---
    label_font = _load_font(34)
    label_text = theme["label"]
    lb = draw.textbbox((0, 0), label_text, font=label_font)
    pad_x, pad_y = 26, 14
    badge_w = (lb[2] - lb[0]) + pad_x * 2
    badge_h = (lb[3] - lb[1]) + pad_y * 2
    badge_pos = (48, 48)
    draw.rounded_rectangle(
        [badge_pos, (badge_pos[0] + badge_w, badge_pos[1] + badge_h)],
        radius=badge_h // 2, fill=accent_rgb + (255,),
    )
    draw.text((badge_pos[0] + pad_x, badge_pos[1] + pad_y - lb[1]), label_text, font=label_font, fill=(255, 255, 255, 255))

    # --- 하단 포인트 바 (카테고리 색상으로 프레임을 잡아줘 시리즈 일관성 + 임팩트) ---
    bar_h = 18
    draw.rectangle([(0, THUMB_SIZE[1] - bar_h), (THUMB_SIZE[0], THUMB_SIZE[1])], fill=accent_rgb + (255,))

    # --- 제목 텍스트 ---
    font = _load_font(72)
    lines = textwrap.wrap(title, width=14)[:3]

    heights = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        heights.append(bbox[3] - bbox[1])
    total_h = sum(heights) + (len(lines) - 1) * 20
    y = (THUMB_SIZE[1] - total_h) / 2 + 20

    for line, lh in zip(lines, heights):
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (THUMB_SIZE[0] - (bbox[2] - bbox[0])) / 2
        draw.text((x + 4, y + 4), line, font=font, fill=(0, 0, 0, 160))
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))
        y += lh + 20

    img.convert("RGB").save(output_path, format="WEBP", quality=82, method=6)


# ---------------------------------------------------------------------
# 브랜드 로고 / 메인 배너 - 사이트 전체에서 재사용되는 고정 아이덴티티
# (카테고리별로 바뀌는 포스트 테마와 달리, 이건 "내 블로그"를 상징하는 고정 이미지)
# ---------------------------------------------------------------------
BRAND_GRADIENT = [(15, 23, 42), (30, 41, 59), (51, 65, 85)]
BRAND_ACCENT = (250, 204, 21)  # 골드 포인트 (랜드마크처럼 눈에 띄는 시그니처 컬러)

LOGO_SIZE = (512, 512)
BANNER_SIZE = (1600, 420)


def generate_site_logo(output_path: str) -> None:
    """사이트 로고(정사각형) - 사이트 제목 첫 글자를 활용한 심볼 마크. 파비콘으로도 재사용됩니다."""
    img = _make_gradient_background(LOGO_SIZE, BRAND_GRADIENT).convert("RGBA")
    draw = ImageDraw.Draw(img)
    w, h = LOGO_SIZE

    # 골드 링(랜드마크 느낌의 원형 프레임)
    margin = 36
    draw.ellipse([margin, margin, w - margin, h - margin], outline=BRAND_ACCENT + (255,), width=10)

    initial = (SITE_TITLE.strip()[:1] or "B")
    font = _load_font(220)
    bbox = draw.textbbox((0, 0), initial, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((w - tw) / 2 - bbox[0], (h - th) / 2 - bbox[1]), initial, font=font, fill=(255, 255, 255, 255))

    img.convert("RGB").save(output_path, format="WEBP", quality=90)


def generate_site_banner(output_path: str) -> None:
    """블로그 최상단 메인 배너(마스트헤드) - 브랜드 랜드마크 역할을 하는 시그니처 이미지."""
    img = _make_gradient_background(BANNER_SIZE, BRAND_GRADIENT).convert("RGBA")
    draw = ImageDraw.Draw(img)
    w, h = BANNER_SIZE

    # 골드 포인트 라인 (상단 랜드마크 느낌의 장식 바)
    draw.rectangle([(0, 0), (w, 8)], fill=BRAND_ACCENT + (255,))

    title_font = _load_font(88)
    tagline_font = _load_font(32)

    tb = draw.textbbox((0, 0), SITE_TITLE, font=title_font)
    tw = tb[2] - tb[0]
    ty = h / 2 - 60
    draw.text(((w - tw) / 2, ty), SITE_TITLE, font=title_font, fill=(255, 255, 255, 255))

    lb = draw.textbbox((0, 0), SITE_TAGLINE, font=tagline_font)
    lw = lb[2] - lb[0]
    draw.text(((w - lw) / 2, ty + 110), SITE_TAGLINE, font=tagline_font, fill=BRAND_ACCENT + (255,))

    img.convert("RGB").save(output_path, format="WEBP", quality=88)


def ensure_brand_assets() -> None:
    """로고/배너를 docs 루트에 항상 최신 상태로 준비해둡니다 (SITE_TITLE 변경 시 자동 반영)."""
    os.makedirs(DOCS_DIR, exist_ok=True)
    logo_path = os.path.join(DOCS_DIR, "logo.webp")
    generate_site_logo(logo_path)
    generate_site_banner(os.path.join(DOCS_DIR, "banner.webp"))

    # 파비콘은 webp 지원이 브라우저마다 달라 PNG로 별도 저장 (호환성)
    favicon_path = os.path.join(DOCS_DIR, "favicon.png")
    with Image.open(logo_path) as im:
        im.convert("RGB").resize((64, 64)).save(favicon_path, format="PNG")


def _coupang_deeplink(search_url: str):
    """쿠팡파트너스 Open API로 실제 수수료가 붙는 딥링크를 발급받습니다. 실패 시 None."""
    if not (COUPANG_ACCESS_KEY and COUPANG_SECRET_KEY):
        return None

    domain = "https://api-gateway.coupang.com"
    path = "/v2/providers/affiliate_open_api/apis/openapi/v1/deeplink"
    try:
        query = urllib.parse.urlencode({"coupangUrls": search_url})
        path_with_query = f"{path}?{query}"
        datetime_str = time.strftime("%y%m%dT%H%M%SZ", time.gmtime())
        message = datetime_str + "GET" + path_with_query
        signature = hmac.new(COUPANG_SECRET_KEY.encode(), message.encode(), hashlib.sha256).hexdigest()
        auth_header = (
            f"CEA algorithm=HmacSHA256, access-key={COUPANG_ACCESS_KEY}, "
            f"signed-date={datetime_str}, signature={signature}"
        )
        resp = requests.get(
            domain + path_with_query,
            headers={"Authorization": auth_header, "Content-Type": "application/json"},
            timeout=8,
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["shortenUrl"]
    except Exception as e:
        print(f"  → [쿠팡 딥링크] 발급 실패, 일반 링크로 대체: {e}")
        return None


def add_ymyl_disclaimer(article: dict) -> dict:
    """대출/보험/정부지원금처럼 잘못된 정보가 실제 금전적 피해로 이어질 수 있는 주제는
    AI 프롬프트 준수 여부와 무관하게 코드 레벨에서 항상 안내문구를 강제로 붙입니다."""
    theme = get_theme(article.get("category", "라이프스타일"))
    if not theme.get("ymyl"):
        return article

    disclaimer = (
        '<div style="background:#fff8e1;border:1px solid #ffe082;border-radius:10px;'
        'padding:14px 18px;margin:24px 0;font-size:0.92em;color:#5d4037;">'
        '⚠️ <b>안내:</b> 이 글은 일반적인 정보 제공 목적으로 작성되었으며, 특정 상품·기관을 보증하지 않습니다. '
        '금리, 자격 요건, 지원금액, 신청 기간 등은 수시로 바뀔 수 있으니 '
        '반드시 해당 금융기관 또는 정부24·관할 지자체 등 공식 채널에서 최신 정보를 확인하세요.'
        '</div>'
    )
    article["html_body"] += disclaimer
    return article


def _relevance_score(article: dict, candidate: dict) -> float:
    """현재 글과 후보 글의 주제 관련도를 점수화합니다.
    - 같은 카테고리면 기본 점수 +3
    - 제목/키워드에 겹치는 단어가 많을수록 가산점"""
    score = 0.0
    if candidate.get("category") == article.get("category", "라이프스타일"):
        score += 3.0

    current_words = set(re.findall(r"[\w가-힣]+", (article.get("title", "") + " " + article.get("keyword", ""))))
    candidate_words = set(re.findall(r"[\w가-힣]+", candidate.get("title", "")))
    overlap = len(current_words & candidate_words)
    score += overlap * 1.5

    return score


def add_internal_link(article: dict) -> dict:
    """본문 끝에 내부링크를 1곳 삽입합니다 (도입부 삽입은 제거).
    단순 '최신글'이 아니라 카테고리 일치 + 제목 단어 겹침으로 관련도를 점수화하고,
    상위 관련 후보 중에서 가중 랜덤으로 골라 매번 다른 글이 걸리도록(유니크하게) 합니다."""
    if not os.path.exists(POSTS_JSON):
        return article
    with open(POSTS_JSON, "r", encoding="utf-8") as f:
        posts = json.load(f)
    if not posts:
        return article

    scored = [(p, _relevance_score(article, p)) for p in posts]
    scored.sort(key=lambda x: x[1], reverse=True)

    top_pool = [p for p, s in scored[:5] if s > 0] or [p for p, s in scored[:5]]
    if not top_pool:
        return article

    weights = [max(s, 0.5) for p, s in scored[:len(top_pool)]]
    pick = random.choices(top_pool, weights=weights, k=1)[0]

    link_html = (
        f'<p style="margin-top:2em;padding-top:1em;border-top:1px dashed #ddd;">'
        f'🔗 이 글도 함께 보면 좋아요: <a href="../{pick["file"]}">{pick["title"]}</a></p>'
    )
    article["html_body"] += link_html
    return article


def _manual_ad_unit() -> str:
    if not (ADSENSE_CLIENT_ID and ADSENSE_SLOT_ID):
        return ""
    return (
        '<div style="margin:28px 0;text-align:center;">'
        f'<ins class="adsbygoogle" style="display:block" data-ad-client="{ADSENSE_CLIENT_ID}" '
        f'data-ad-slot="{ADSENSE_SLOT_ID}" data-ad-format="auto" data-full-width-responsive="true"></ins>'
        '<script>(adsbygoogle = window.adsbygoogle || []).push({});</script>'
        '</div>'
    )


def insert_manual_ads(article: dict) -> dict:
    """시선이 가장 많이 머무는 '본문 상단 소제목 위'에 광고를 1개 수동 배치합니다.
    글 하단 광고는 POST_TEMPLATE에서 related 섹션 뒤에 별도로 추가됩니다.
    ADSENSE_SLOT_ID 미설정 시 아무 것도 삽입되지 않습니다 (자동광고만 동작)."""
    ad_html = _manual_ad_unit()
    if not ad_html:
        return article

    idx = article["html_body"].find("<h2")
    if idx != -1:
        article["html_body"] = article["html_body"][:idx] + ad_html + article["html_body"][idx:]
    else:
        article["html_body"] += ad_html
    return article


def add_coupang_markup(article: dict) -> dict:
    keyword = article["keyword"]
    search_url = f"https://www.coupang.com/np/search?q={urllib.parse.quote(keyword)}"
    if COUPANG_PARTNER_TAG:
        search_url += f"&lptag={COUPANG_PARTNER_TAG}"

    link = _coupang_deeplink(search_url) or search_url
    link_type = "쿠팡파트너스 딥링크" if link != search_url else "일반 검색 링크"
    print(f"  → 마크업 링크 방식: {link_type}")

    extra_html = (
        f'<h2>관련 추천 상품</h2>'
        f'<p><a href="{link}" target="_blank" rel="nofollow sponsored">{keyword} 관련 인기 상품 보러가기</a></p>'
        '<p style="font-size:0.85em;color:#888;">이 포스팅은 쿠팡 파트너스 활동의 일환으로, '
        '이에 따른 일정액의 수수료를 제공받습니다.</p>'
    )
    article["html_body"] += extra_html
    return article


def _font_family_name(font_param: str) -> str:
    return font_param.split(":")[0].replace("+", " ")


def _build_related_html(exclude_slug: str) -> str:
    """이전에 발행된 글 중 최신 3개를 관련글로 보여줍니다 (체류시간/페이지뷰 증가 → 광고수익에 도움)."""
    if not os.path.exists(POSTS_JSON):
        return ""
    with open(POSTS_JSON, "r", encoding="utf-8") as f:
        posts = json.load(f)
    posts = [p for p in posts if p.get("file") != exclude_slug][:3]
    if not posts:
        return ""

    cards = "\n".join(
        f'<a class="related-card" href="../{p["file"]}"><img src="../{p["thumb"]}" alt="{p["title"]}" loading="lazy">'
        f'<span>{p["title"]}</span></a>'
        for p in posts
    )
    return f'<div class="related"><h3>📌 함께 보면 좋은 글</h3><div class="related-grid">{cards}</div></div>'


def save_post(article: dict):
    os.makedirs(POSTS_DIR, exist_ok=True)
    os.makedirs(os.path.join(DOCS_DIR, "thumbs"), exist_ok=True)

    category = article.get("category", "라이프스타일")
    theme = get_theme(category)

    slug = slugify(article["keyword"])
    today = datetime.now().strftime("%Y-%m-%d")
    thumb_filename = f"{slug}-{today}.webp"
    post_filename = f"{slug}-{today}.html"

    generate_thumbnail(article["title"], os.path.join(DOCS_DIR, "thumbs", thumb_filename), theme, category)

    post_url = f"{SITE_URL}/posts/{post_filename}" if SITE_URL else f"posts/{post_filename}"
    thumb_url = f"{SITE_URL}/thumbs/{thumb_filename}" if SITE_URL else f"../thumbs/{thumb_filename}"

    title = article["title"]
    meta_description = article.get("meta_description", "")
    json_ld = build_json_ld(article, post_url, thumb_url, today)
    related_html = _build_related_html(exclude_slug=f"posts/{post_filename}")
    decor_html = build_decor_html(theme, seed=slug)

    html = POST_TEMPLATE.format(
        title=title,
        meta_description=meta_description,
        date=today,
        html_body=article["html_body"],
        thumb_filename=thumb_filename,
        canonical_url=post_url,
        thumb_url=thumb_url,
        json_ld=json_ld,
        ga_snippet=_ga_snippet(),
        adsense_snippet=_adsense_snippet(),
        font=theme["font"],
        font_family=_font_family_name(theme["font"]),
        accent=theme["accent"],
        badge=theme["badge"],
        related_html=related_html,
        decor_html=decor_html,
        bottom_ad=_manual_ad_unit(),
        search_console_meta=_search_console_meta(),
    )
    with open(os.path.join(POSTS_DIR, post_filename), "w", encoding="utf-8") as f:
        f.write(html)

    post_meta = {
        "title": title,
        "file": f"posts/{post_filename}",
        "thumb": f"thumbs/{thumb_filename}",
        "date": today,
        "category": category,
        "accent": theme["accent"],
        "badge": theme["badge"],
    }
    local_thumb_path = os.path.join(DOCS_DIR, "thumbs", thumb_filename)
    return post_meta, json_ld, thumb_url, local_thumb_path, post_url


def update_index(new_post: dict) -> list:
    os.makedirs(DOCS_DIR, exist_ok=True)
    posts = []
    if os.path.exists(POSTS_JSON):
        with open(POSTS_JSON, "r", encoding="utf-8") as f:
            posts = json.load(f)

    posts.insert(0, new_post)
    with open(POSTS_JSON, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)

    hero_posts, mid_posts, bottom_posts = posts[:1], posts[1:3], posts[3:]

    hero_html = ""
    if hero_posts:
        p = hero_posts[0]
        hero_html = (
            '<div class="tier-label">🔥 최신 이야기</div>'
            f'<a class="hero" href="{p["file"]}"><img src="{p["thumb"]}" alt="{p["title"]}" loading="eager" fetchpriority="high">'
            f'<div class="hero-body"><span class="hero-badge" style="background:{p.get("accent", "#4a90d9")}">'
            f'{p.get("badge", "✨ 라이프스타일")}</span>'
            f'<div class="hero-title">{p["title"]}</div>'
            f'<div class="date">{p["date"]}</div></div></a>'
        )

    mid_html = ""
    if mid_posts:
        cards = "\n".join(
            f'<a class="mid-card" href="{p["file"]}"><img src="{p["thumb"]}" alt="{p["title"]}" loading="lazy">'
            f'<div class="mid-body"><span class="badge-sm" style="background:{p.get("accent", "#4a90d9")}">'
            f'{p.get("badge", "✨ 라이프스타일")}</span>'
            f'<div class="mid-title">{p["title"]}</div>'
            f'<div class="date">{p["date"]}</div></div></a>'
            for p in mid_posts
        )
        mid_html = f'<div class="tier-label">📖 다음 이야기</div><div class="mid-grid">{cards}</div>'

    bottom_html = ""
    if bottom_posts:
        cards = "\n".join(
            f'<a class="bottom-card" href="{p["file"]}"><img src="{p["thumb"]}" alt="{p["title"]}" loading="lazy">'
            f'<div class="bottom-body"><span class="badge-sm" style="background:{p.get("accent", "#4a90d9")}">'
            f'{p.get("badge", "✨ 라이프스타일")}</span>'
            f'<div class="bottom-title">{p["title"]}</div></div></a>'
            for p in bottom_posts
        )
        bottom_html = f'<div class="tier-label">🗂️ 지난 글 모아보기</div><div class="bottom-grid">{cards}</div>'

    with open(os.path.join(DOCS_DIR, "index.html"), "w", encoding="utf-8") as f:
        category_pills = "".join(
            f'<span class="pill" style="background:{t["accent"]}">{t["badge"]}</span>'
            for t in CATEGORY_THEMES.values()
        )
        f.write(INDEX_TEMPLATE.format(
            site_title=SITE_TITLE,
            site_tagline=SITE_TAGLINE,
            site_url=SITE_URL or ".", ga_snippet=_ga_snippet(),
            adsense_snippet=_adsense_snippet(),
            fonts_url=_google_fonts_url(),
            hero_html=hero_html, mid_html=mid_html, bottom_html=bottom_html,
            blog_json_ld=build_blog_index_json_ld(posts),
            category_pills=category_pills,
            search_console_meta=_search_console_meta(),
            footer_html=build_footer_html(),
        ))

    return posts


STATIC_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{page_title} - {site_title}</title>
<link rel="icon" type="image/png" href="favicon.png">{search_console_meta}{ga_snippet}{adsense_snippet}
<style>
  body {{ max-width: 680px; margin: 0 auto; padding: 40px 20px 60px; font-family: 'Noto Sans KR', -apple-system, sans-serif; line-height: 1.8; color: #222; }}
  h1 {{ font-size: 1.6em; }}
  h2 {{ font-size: 1.15em; margin-top: 1.6em; }}
  a.back {{ color: #4a90d9; text-decoration: none; display:inline-block; margin-bottom: 20px; }}
</style>
</head>
<body>
<a class="back" href="index.html">← 홈으로</a>
<h1>{page_title}</h1>
{page_body}
</body>
</html>
"""


def build_footer_html() -> str:
    return (
        '<div class="site-footer">'
        '<a href="about.html">블로그 소개</a>·'
        '<a href="privacy.html">개인정보처리방침</a>·'
        '<a href="contact.html">문의하기</a>'
        f'<div style="margin-top:8px;">© {datetime.now().year} {SITE_TITLE}</div>'
        '</div>'
    )


def generate_static_pages() -> None:
    """About / Privacy Policy / Contact 페이지를 생성합니다 (SEO 신뢰도 + 애드센스 승인 필수요건).
    이미 있으면 건드리지 않고, 없을 때만 새로 만듭니다 (직접 문구를 수정해도 덮어쓰지 않기 위함)."""
    os.makedirs(DOCS_DIR, exist_ok=True)
    common_kwargs = dict(
        site_title=SITE_TITLE,
        search_console_meta=_search_console_meta(),
        ga_snippet=_ga_snippet(),
        adsense_snippet=_adsense_snippet(),
    )

    pages = {
        "about.html": (
            "블로그 소개",
            f"<p>{SITE_TITLE}에 오신 것을 환영합니다.</p>"
            f"<p>{SITE_TAGLINE}</p>"
            "<p>이 블로그는 다양한 주제의 정보를 정리해서 소개하며, 콘텐츠 제작 과정 일부에 "
            "AI 도구를 활용하고 있습니다. 게시된 정보는 참고용이며, 중요한 결정을 내리실 때는 "
            "반드시 공식 출처를 함께 확인해주세요.</p>",
        ),
        "privacy.html": (
            "개인정보처리방침",
            "<p>본 블로그는 구글 애널리틱스(GA4) 및 구글 애드센스를 통해 방문자 통계와 광고를 "
            "제공할 수 있습니다. 이 과정에서 쿠키(Cookie)가 사용될 수 있으며, 쿠키를 통해 "
            "수집되는 정보에는 개인을 직접 식별할 수 있는 정보는 포함되지 않습니다.</p>"
            "<h2>쿠키 및 광고</h2>"
            "<p>구글을 포함한 제3자 광고 공급업체는 쿠키를 사용하여 사용자의 이전 방문 기록을 "
            "기반으로 광고를 게재합니다. 이용자는 "
            '<a href="https://adssettings.google.com" target="_blank">구글 광고 설정</a>에서 '
            "맞춤 광고를 비활성화할 수 있습니다.</p>"
            "<h2>문의</h2>"
            "<p>개인정보 관련 문의사항은 문의하기 페이지를 통해 연락 주시기 바랍니다.</p>",
        ),
        "contact.html": (
            "문의하기",
            "<p>블로그 콘텐츠 관련 문의, 협업 제안, 오류 신고 등은 아래 이메일로 연락 주세요.</p>"
            "<p><b>이메일:</b> 이 페이지의 문구를 직접 열어 본인의 연락처로 수정해주세요.</p>",
        ),
    }

    for filename, (page_title, page_body) in pages.items():
        path = os.path.join(DOCS_DIR, filename)
        if os.path.exists(path):
            continue  # 이미 있으면 (직접 수정했을 수 있으니) 덮어쓰지 않음
        with open(path, "w", encoding="utf-8") as f:
            f.write(STATIC_PAGE_TEMPLATE.format(page_title=page_title, page_body=page_body, **common_kwargs))
        print(f"  → [설정] {filename} 생성됨 (내용은 실제 정보로 직접 수정 권장)")


def update_dashboard(posts: list) -> None:
    rows = "\n".join(
        f'<tr><td>{p["date"]}</td><td>{p["title"]}</td><td><a href="{p["file"]}">보기</a></td></tr>'
        for p in posts
    )
    with open(os.path.join(DOCS_DIR, "dashboard.html"), "w", encoding="utf-8") as f:
        f.write(DASHBOARD_TEMPLATE.format(site_title=SITE_TITLE, post_count=len(posts), rows=rows))


def update_seo_files(posts: list) -> None:
    """SEO용 sitemap.xml / robots.txt를 매번 최신 글 목록 기준으로 갱신합니다."""
    if not SITE_URL:
        print("  → [SEO] SITE_URL이 설정되지 않아 sitemap.xml/robots.txt 생성을 건너뜁니다.")
        return

    url_entries = "\n".join(f"<url><loc>{SITE_URL}/{p['file']}</loc></url>" for p in posts)
    with open(os.path.join(DOCS_DIR, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write(SITEMAP_TEMPLATE.format(site_url=SITE_URL, url_entries=url_entries))

    with open(os.path.join(DOCS_DIR, "robots.txt"), "w", encoding="utf-8") as f:
        f.write(ROBOTS_TXT.format(site_url=SITE_URL))


# ---------------------------------------------------------------------
# 구글 블로거(Blogger) 동시 발행 - v4
# ---------------------------------------------------------------------

def _blogger_configured() -> bool:
    return bool(BLOGGER_BLOG_ID and GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and GOOGLE_REFRESH_TOKEN)


def _get_blogger_access_token() -> str:
    """리프레시 토큰으로 새 access token을 발급받습니다 (매 실행마다 자동, 사람 개입 불필요)."""
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "refresh_token": GOOGLE_REFRESH_TOKEN,
            "grant_type": "refresh_token",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _make_blogger_safe_html(html_body: str) -> str:
    """html_body 안에는 GitHub Pages 폴더 구조 기준 상대경로 링크(../posts/, ../thumbs/)가
    섞여 있을 수 있습니다 (같은 카테고리 이전 글로의 내부링크 등). 이 상대경로는 블로거에는
    존재하지 않는 주소라 그대로 두면 '페이지를 찾을 수 없습니다' 오류가 납니다.
    SITE_URL이 설정되어 있으면 절대경로로 바꾸고, 없으면 깨진 링크를 만들지 않도록 태그만 제거합니다."""
    if SITE_URL:
        html_body = html_body.replace('href="../posts/', f'href="{SITE_URL}/posts/')
        html_body = html_body.replace('href="../thumbs/', f'href="{SITE_URL}/thumbs/')
        html_body = html_body.replace('src="../thumbs/', f'src="{SITE_URL}/thumbs/')
    else:
        # SITE_URL이 없으면 절대경로를 만들 수 없으니, 깨진 링크 대신 일반 텍스트로 되돌립니다.
        html_body = re.sub(r'<a href="\.\./(posts|thumbs)/[^"]*"[^>]*>(.*?)</a>', r"\2", html_body)
    return html_body


def publish_to_blogger(article: dict, canonical_url: str, thumb_url: str, local_thumb_path: str) -> None:
    """같은 글을 구글 블로거에도 발행합니다. 미설정/실패해도 전체 파이프라인은 계속 진행됩니다."""
    if not _blogger_configured():
        print("  → [블로거] 관련 Secrets가 없어 건너뜁니다 (GitHub Pages만 발행).")
        return

    try:
        access_token = _get_blogger_access_token()
        theme = get_theme(article.get("category", "라이프스타일"))
        today = datetime.now().strftime("%Y-%m-%d")
        # 블로거 채널에는 Article 대신 BlogPosting 스키마 사용 (블로그 플랫폼 권장 타입)
        blogger_json_ld = build_json_ld(article, canonical_url, thumb_url, today, platform="blogger")

        # 썸네일을 외부 URL 링크가 아니라 base64로 직접 본문에 박아 넣습니다.
        # → SITE_URL 설정 여부나 GitHub Pages 배포 상태와 무관하게 이미지가 항상 정상 표시됩니다
        #   (이전에 "이미지 손상"이 발생했던 원인이 바로 외부 링크 의존성이었습니다).
        try:
            with open(local_thumb_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("ascii")
            img_src = f"data:image/webp;base64,{img_b64}"
        except Exception as e:
            print(f"  → [블로거] 썸네일 base64 인코딩 실패, 외부 링크로 대체: {e}")
            img_src = thumb_url

        content_html = (
            f'<img src="{img_src}" style="max-width:100%;border-radius:8px;" alt="{article["title"]}">'
            f'<span style="display:inline-block;background:{theme["accent"]};color:#fff;font-size:0.85em;'
            f'font-weight:bold;padding:4px 12px;border-radius:999px;margin:14px 0 4px;">{theme["badge"]}</span>'
            f'{_make_blogger_safe_html(article["html_body"])}'
            f'<script type="application/ld+json">{blogger_json_ld}</script>'
        )

        url = f"https://www.googleapis.com/blogger/v3/blogs/{BLOGGER_BLOG_ID}/posts/"
        payload = {"title": article["title"], "content": content_html}
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        print(f"  → [블로거] 발행 완료: {result.get('url', '(URL 확인 불가)')}")
    except Exception as e:
        print(f"  → [블로거] 발행 실패 (GitHub Pages 발행은 정상 진행됨): {e}")


def ensure_nojekyll() -> None:
    """GitHub Pages가 Jekyll로 문서를 가공하지 않고 있는 그대로 서빙하게 합니다.
    이 파일이 없으면 Jekyll이 파일명/구조를 자기 방식대로 해석하면서
    링크가 깨지거나 일부 파일이 누락되는 문제가 생길 수 있습니다."""
    os.makedirs(DOCS_DIR, exist_ok=True)
    nojekyll_path = os.path.join(DOCS_DIR, ".nojekyll")
    if not os.path.exists(nojekyll_path):
        open(nojekyll_path, "w").close()
        print("  → [설정] .nojekyll 파일 생성 (Jekyll 가공 비활성화)")


def run():
    title = get_title_from_args_or_queue()
    print(f"[처리 시작] 제목: {title}")

    ensure_nojekyll()
    ensure_brand_assets()
    generate_static_pages()

    article = generate_article(title)
    print(f"  → 글 생성 완료: {article['title']}")

    article = add_internal_link(article)
    article = insert_manual_ads(article)
    article = add_coupang_markup(article)
    article = add_ymyl_disclaimer(article)
    post_meta, json_ld, thumb_url, local_thumb_path, post_url = save_post(article)
    posts = update_index(post_meta)
    update_dashboard(posts)
    update_seo_files(posts)
    publish_to_blogger(article, post_url, thumb_url, local_thumb_path)

    print(f"  → 저장 완료: docs/{post_meta['file']}, docs/{post_meta['thumb']}")
    print(f"  → 대시보드/사이트맵 갱신 완료")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        print(f"[오류] {e}")
        sys.exit(1)
