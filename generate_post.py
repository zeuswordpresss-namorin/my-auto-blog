# -*- coding: utf-8 -*-
"""
GitHub Actions 위에서 실행되는 자동 블로그 파이프라인 스크립트 (v4.1 - 버그 수정 및 안정화 버전)
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
import time
import urllib.parse
from datetime import datetime

import requests
from PIL import Image, ImageDraw, ImageFont

# =====================================================================
# 환경변수로 받는 설정값
# =====================================================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
SITE_TITLE = os.environ.get("SITE_TITLE", "내 자동 블로그")
SITE_TAGLINE = os.environ.get("SITE_TAGLINE", "매일 자동으로 업데이트되는 정보 큐레이션 블로그")
SITE_URL = os.environ.get("SITE_URL", "").rstrip("/")
GA_MEASUREMENT_ID = os.environ.get("GA_MEASUREMENT_ID", "")
GOOGLE_SITE_VERIFICATION = os.environ.get("GOOGLE_SITE_VERIFICATION", "")
ADSENSE_CLIENT_ID = os.environ.get("ADSENSE_CLIENT_ID", "")
ADSENSE_SLOT_ID = os.environ.get("ADSENSE_SLOT_ID", "")

COUPANG_PARTNER_TAG = os.environ.get("COUPANG_PARTNER_TAG", "")
COUPANG_ACCESS_KEY = os.environ.get("COUPANG_ACCESS_KEY", "")
COUPANG_SECRET_KEY = os.environ.get("COUPANG_SECRET_KEY", "")

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
6. 가독성을 위해 본문 중 최소 1곳에 <table> (수치/스펙 비교용 정리표) 또는 <ul>/<ol> 목록을 반드시 포함한다.
   단, 질문-답변(Q&A) 내용은 절대 <table>로 만들지 않는다 (표 형태는 모바일에서 깨지기 쉬움).
   FAQPage 타입을 고른 경우, 본문에는 Q&A를 별도로 나열하지 않는다 (faq_items로 충분하며, 화면에는 별도 섹션으로 자동 표시됨).
7. "product_keyword"에는 이 글 내용과 실제로 관련된, 쿠팡에서 검색했을 때 진짜 상품이 나올 만한
   쇼핑 키워드(2~4단어)를 넣는다. 예: 육아 관련 글 → "신생아 용품 세트", 게임 패치 소식 → "게이밍 마우스".
   연예인 뉴스, 시사/정치, 날씨 등 상품과 자연스럽게 연결되지 않는 주제라면 억지로 만들지 말고
   반드시 빈 문자열("")로 둔다 (빈 문자열이면 상품 추천 섹션 자체가 생략됨).
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
  "category": "위 10개 중 하나",
  "product_keyword": "쇼핑 키워드 또는 빈 문자열"
}
html_body는 <h2>, <p>, <table>, <ul> 등을 사용한 HTML 조각이어야 한다."""

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
<script async src="[https://www.googletagmanager.com/gtag/js?id=](https://www.googletagmanager.com/gtag/js?id=){GA_MEASUREMENT_ID}"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', '{GA_MEASUREMENT_ID}');
</script>"""

ENABLE_AUTO_TRANSLATE = os.environ.get("ENABLE_AUTO_TRANSLATE", "true").strip().lower() != "false"

def _translate_widget() -> str:
    if not ENABLE_AUTO_TRANSLATE:
        return ""
    return """
<div style="position:fixed;top:10px;right:10px;z-index:999;">
  <button onclick="var e=document.getElementById('gt-box');e.style.display=(e.style.display==='none'||!e.style.display)?'block':'none';"
    style="width:38px;height:38px;border-radius:50%;border:none;background:#fff;box-shadow:0 2px 8px rgba(0,0,0,0.25);font-size:17px;cursor:pointer;line-height:1;">🌐</button>
  <div id="gt-box" style="display:none;margin-top:6px;background:#fff;padding:6px 8px;border-radius:10px;box-shadow:0 2px 10px rgba(0,0,0,0.18);">
    <div id="google_translate_element"></div>
  </div>
</div>
<script>
function googleTranslateElementInit() {
  new google.translate.TranslateElement({pageLanguage: 'ko', autoDisplay: false}, 'google_translate_element');
}
</script>
<script src="//[translate.google.com/translate_a/element.js?cb=googleTranslateElementInit](https://translate.google.com/translate_a/element.js?cb=googleTranslateElementInit)"></script>"""

def _adsense_snippet() -> str:
    if not ADSENSE_CLIENT_ID:
        return ""
    return (
        f'\n<script async src="[https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js](https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js)'
        f'?client={ADSENSE_CLIENT_ID}" crossorigin="anonymous"></script>'
    )

def build_faq_section_html(article: dict, accent: str = "#4a90d9") -> str:
    if article.get("schema_type") != "FAQPage" or not article.get("faq_items"):
        return ""

    cards = []
    for i, qa in enumerate(article["faq_items"], 1):
        question = qa.get("question", "")
        answer = qa.get("answer", "")
        cards.append(
            f'<details style="margin:14px 0;background:#f7f8fa;border-left:4px solid {accent};'
            'border-radius:8px;padding:2px 18px;">'
            '<summary style="cursor:pointer;padding:14px 0;font-family:Georgia,\'Noto Serif KR\',serif;'
            f'font-weight:800;font-size:1.08em;color:#111;">Q{i}. {question}</summary>'
            '<p style="margin:0;padding:0 0 16px;font-family:\'Noto Sans KR\',-apple-system,sans-serif;'
            f'font-weight:400;color:#555;line-height:1.75;">A. {answer}</p>'
            '</details>'
        )

    return (
        '<h2 style="margin-top:2em;">자주 묻는 질문 <span style="font-size:0.6em;color:#999;font-weight:400;">'
        '(탭하면 펼쳐져요)</span></h2>'
        + "".join(cards)
    )

def build_json_ld(article: dict, canonical_url: str, thumb_url: str, date: str, platform: str = "github") -> str:
    schema_type = article.get("schema_type", "Article")
    title = article["title"]
    meta_description = article.get("meta_description", "")
    article_type = "BlogPosting" if platform == "blogger" else "Article"

    if schema_type == "FAQPage" and article.get("faq_items"):
        data = {
            "@context": "[https://schema.org](https://schema.org)",
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
            "@context": "[https://schema.org](https://schema.org)",
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
            "@context": "[https://schema.org](https://schema.org)",
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
    graph_data = {"@context": "[https://schema.org](https://schema.org)", "@graph": [data, breadcrumb]}

    print(f"  → [스키마 마크업] AI가 선택한 타입: {schema_type} (+ BreadcrumbList)")
    return json.dumps(graph_data, ensure_ascii=False, indent=2)

def build_blog_index_json_ld(posts: list) -> str:
    data = {
        "@context": "[https://schema.org](https://schema.org)",
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
<link rel="preconnect" href="[https://fonts.googleapis.com](https://fonts.googleapis.com)">
<link href="[https://fonts.googleapis.com/css2?family=](https://fonts.googleapis.com/css2?family=){font}&family=Noto+Sans+KR:wght@400;700&display=swap" rel="stylesheet">
<script type="application/ld+json">
{json_ld}
</script>{ga_snippet}{adsense_snippet}
<style>
  * {{ box-sizing: border-box; }}
  html {{ -webkit-text-size-adjust: 100%; }}
  body {{ position: relative; width: 100%; max-width: 720px; margin: 0 auto; padding: 0 clamp(16px, 4vw, 20px) 60px; font-family: 'Noto Sans KR', -apple-system, sans-serif; line-height: 1.75; color: #1a1a1a; background: #fafafa; overflow-x: hidden; }}
  img {{ max-width: 100%; height: auto; }}
  .decor-layer {{ position: absolute; inset: 0; overflow: hidden; pointer-events: none; z-index: 0; }}
  .decor-item {{ position: absolute; filter: grayscale(0%); user-select: none; }}
  .content {{ position: relative; z-index: 1; }}
  .hero {{ margin: 0 -20px 24px; position: relative; }}
  .hero img {{ width: 100%; aspect-ratio: 16/9; object-fit: cover; display: block; }}
  .badge {{ display: inline-block; background: {accent}; color: #fff; font-size: clamp(0.75em, 2.2vw, 0.85em); font-weight: 700; padding: 5px 14px; border-radius: 999px; margin: 20px 0 10px; }}
  h1 {{ font-family: '{font_family}', 'Noto Sans KR', sans-serif; font-size: clamp(1.4em, 5vw, 1.9em); line-height: 1.35; margin: 0 0 8px; word-break: keep-all; }}
  h2 {{ font-family: '{font_family}', 'Noto Sans KR', sans-serif; font-size: clamp(1.1em, 4vw, 1.35em); margin-top: 2em; padding: 10px 14px; background: linear-gradient(90deg, {accent}22, transparent); border-left: 5px solid {accent}; border-radius: 4px; position: relative; z-index: 1; word-break: keep-all; }}
  p {{ margin: 1em 0; position: relative; z-index: 1; }}
  table {{ width: 100%; border-collapse: collapse; display: block; overflow-x: auto; white-space: nowrap; }}
  a.back {{ display: inline-block; margin: 20px 0; color: {accent}; text-decoration: none; font-weight: 700; position: relative; z-index: 1; }}
  .meta {{ color: #999; font-size: 0.85em; margin-bottom: 4px; }}
  .related {{ margin-top: 60px; padding-top: 24px; border-top: 2px solid #eee; }}
  .related h3 {{ font-size: 1.1em; margin-bottom: 14px; }}
  .related-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 14px; }}
  .related-card {{ text-decoration: none; color: #1a1a1a; }}
  .related-card img {{ width: 100%; aspect-ratio: 16/9; object-fit: cover; border-radius: 10px; margin-bottom: 6px; }}
  .related-card span {{ font-size: 0.88em; font-weight: 500; }}
  .post-nav {{ display: flex; justify-content: space-between; gap: 10px; margin: 30px 0; flex-wrap: wrap; }}
  .post-nav a {{ display: flex; align-items: center; gap: 8px; text-decoration: none; color: #333; background: #fff; border: 1px solid #eee; border-radius: 999px; padding: 6px 16px 6px 6px; font-size: 0.85em; max-width: 100%; }}
  .post-nav img {{ width: 28px; height: 28px; border-radius: 50%; object-fit: cover; flex-shrink: 0; }}
  .post-nav .nav-icon {{ width: 28px; height: 28px; border-radius: 50%; background: {accent}; color: #fff; display:flex; align-items:center; justify-content:center; font-size: 14px; flex-shrink: 0; }}
  .post-nav span {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  @media (max-width: 480px) {{
    .related-grid {{ grid-template-columns: 1fr 1fr; }}
    .post-nav a {{ font-size: 0.78em; flex: 1 1 100%; }}
  }}
  @media (min-width: 900px) {{
    body {{ max-width: 760px; }}
  }}
  .translate-widget {{ position: fixed; top: 10px; right: 10px; z-index: 999; font-size: 0.8em; }}
  body {{ top: 0 !important; }}
  .goog-te-banner-frame {{ display: none !important; }}
</style>
</head>
<body>
{translate_widget}
{decor_html}
<div class="content">
<a class="back" href="../index.html">← 목록으로</a>
<div class="hero"><img src="../thumbs/{thumb_filename}" alt="{title}" loading="eager" fetchpriority="high"></div>
<span class="badge">{badge}</span>
<h1>{title}</h1>
<p class="meta">{date}</p>
{html_body}
{post_nav}
{related_html}
{bottom_ad}
</div>
</body>
</html>
"""

ALL_THEME_FONTS = sorted({t["font"] for t in CATEGORY_THEMES.values()})

def _google_fonts_url() -> str:
    families = "&family=".join(ALL_THEME_FONTS)
    return f"[https://fonts.googleapis.com/css2?family=](https://fonts.googleapis.com/css2?family=){families}&family=Noto+Sans+KR:wght@400;700;900&display=swap"

INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{site_title}</title>
<meta name="description" content="{site_title} - 자동으로 업데이트되는 블로그">
<link rel="canonical" href="{site_url}/">
<link rel="icon" type="image/png" href="favicon.png">{search_console_meta}
<link rel="preconnect" href="[https://fonts.googleapis.com](https://fonts.googleapis.com)">
<link href="{fonts_url}" rel="stylesheet">
<script type="application/ld+json">
{blog_json_ld}
</script>{ga_snippet}{adsense_snippet}
<style>
  * {{ box-sizing: border-box; }}
  html {{ -webkit-text-size-adjust: 100%; }}
  body {{ max-width: 1000px; margin: 0 auto; padding: 0 0 60px; font-family: 'Noto Sans KR', -apple-system, sans-serif; background:#f5f5f7; color:#1a1a1a; }}
  img {{ max-width: 100%; height: auto; }}
  .masthead {{ position: relative; margin-bottom: 26px; }}
  .masthead img {{ width: 100%; aspect-ratio: 1600/420; object-fit: cover; display:block; }}
  .masthead-inner {{ padding: 0 clamp(14px, 4vw, 20px); }}
  .brand-row {{ display:flex; align-items:center; gap:12px; margin: 18px 0 4px; flex-wrap: wrap; }}
  .brand-row img.logo {{ width:44px; height:44px; border-radius:50%; box-shadow: 0 2px 8px rgba(0,0,0,0.15); }}
  h1.site-title {{ font-family: 'Jua', sans-serif; font-size: clamp(1.2em, 4.5vw, 1.6em); margin:0; word-break: keep-all; }}
  .dash-link {{ margin-left:auto; font-size: clamp(0.7em, 2.5vw, 0.75em); color:#888; text-decoration:none; background:#eee; padding:6px 14px; border-radius:999px; }}
  .intro {{ color:#555; font-size:0.95em; margin: 4px 0 16px; line-height:1.6; word-break: keep-all; }}
  .pill-row {{ display:flex; flex-wrap:wrap; gap:8px; margin-bottom: 10px; }}
  .pill {{ font-size:0.78em; font-weight:700; color:#fff; padding:5px 13px; border-radius:999px; }}
  .content-wrap {{ padding: 0 clamp(14px, 4vw, 20px); }}
  .tier-label {{ font-size: 0.85em; font-weight:900; color:#aaa; letter-spacing:2px; margin: 34px 0 12px; text-transform:uppercase; }}
  .tier-label:first-of-type {{ margin-top: 10px; }}

  .hero {{ display:block; text-decoration:none; color:#1a1a1a; background:#fff; border-radius:20px; overflow:hidden; box-shadow: 0 6px 24px rgba(0,0,0,0.10); }}
  .hero img {{ width:100%; aspect-ratio: 21/9; object-fit:cover; display:block; }}
  .hero-body {{ padding: clamp(16px, 4vw, 22px) clamp(18px, 5vw, 26px) 28px; }}
  .hero-badge {{ display:inline-block; font-size:0.8em; font-weight:700; color:#fff; padding:5px 14px; border-radius:999px; margin-bottom:12px; }}
  .hero-title {{ font-size: clamp(1.25em, 4.5vw, 1.7em); font-weight:800; line-height:1.35; word-break: keep-all; }}

  .mid-grid {{ display:grid; grid-template-columns: 1fr 1fr; gap:18px; }}
  .mid-card {{ text-decoration:none; color:#1a1a1a; background:#fff; border-radius:16px; overflow:hidden; box-shadow: 0 3px 14px rgba(0,0,0,0.08); transition: transform .15s ease; }}
  .mid-card:hover {{ transform: translateY(-3px); }}
  .mid-card img {{ width:100%; aspect-ratio:16/9; object-fit:cover; display:block; }}
  .mid-body {{ padding: 14px 16px 18px; }}
  .mid-title {{ font-weight:700; font-size:clamp(0.92em, 3vw, 1.08em); line-height:1.4; word-break: keep-all; }}

  .bottom-grid {{ display:grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap:14px; }}
  .bottom-card {{ text-decoration:none; color:#1a1a1a; background:#fff; border-radius:10px; overflow:hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
  .bottom-card img {{ width:100%; aspect-ratio:16/10; object-fit:cover; display:block; }}
  .bottom-body {{ padding: 8px 10px 12px; }}
  .bottom-title {{ font-weight:600; font-size:0.85em; line-height:1.35; word-break: keep-all; }}

  .badge-sm {{ display:inline-block; font-size:0.65em; font-weight:700; color:#fff; padding:2px 8px; border-radius:999px; margin-bottom:5px; }}
  .date {{ color: #999; font-size: 0.78em; margin-top: 5px; }}
  .site-footer {{ margin-top: 50px; padding: 24px 20px; border-top: 1px solid #e2e2e2; text-align:center; color:#999; font-size:0.82em; }}
  .site-footer a {{ color:#777; text-decoration:none; margin: 0 8px; }}
  .site-footer a:hover {{ color:#b45309; }}

  @media (max-width: 480px) {{
    .masthead img {{ aspect-ratio: 1600/620; }}
    .hero img {{ aspect-ratio: 16/9; }}
    .mid-grid {{ grid-template-columns: 1fr; gap: 14px; }}
    .bottom-grid {{ grid-template-columns: repeat(2, 1fr); }}
  }}
  @media (min-width: 1000px) {{
    .bottom-grid {{ grid-template-columns: repeat(5, 1fr); }}
  }}
  .translate-widget {{ position: fixed; top: 10px; right: 10px; z-index: 999; font-size: 0.8em; }}
  body {{ top: 0 !important; }}
  .goog-te-banner-frame {{ display: none !important; }}
</style>
</head>
<body>
{translate_widget}
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
  <a href="[https://analytics.google.com](https://analytics.google.com)" target="_blank">analytics.google.com 바로가기</a>
</div>

<div class="card">
  <b>수익(쿠팡 마크업 수수료) 확인</b><br>
  쿠팡파트너스 앱 또는 사이트에서 클릭수/수익을 확인하세요.<br>
  <a href="[https://partners.coupang.com](https://partners.coupang.com)" target="_blank">partners.coupang.com 바로가기</a>
</div>

<div class="card">
  <b>광고 수익(애드센스) 확인</b><br>
  플레이스토어 "Google AdSense" 앱 설치 후 페이지뷰/광고 수익(전면광고 포함)을 확인하세요.<br>
  <a href="[https://www.google.com/adsense](https://www.google.com/adsense)" target="_blank">adsense.google.com 바로가기</a>
</div>

<div class="card">
  <b>검색 노출 확인 (Google Search Console)</b><br>
  사이트가 구글 검색에 얼마나 노출/클릭되는지 확인하세요. 최초 1회 소유권 인증이 필요합니다.<br>
  <a href="[https://search.google.com/search-console](https://search.google.com/search-console)" target="_blank">[search.google.com/search-console](https://search.google.com/search-console) 바로가기</a>
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
<urlset xmlns="[http://www.sitemaps.org/schemas/sitemap/0.9](http://www.sitemaps.org/schemas/sitemap/0.9)">
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
            
            # [버그 수정]: JSON 마크다운 기호 제거 후 정규식으로 순수 { } 객체만 정밀 검출
            cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                cleaned = match.group(0)
                
            decoder = json.JSONDecoder()
            article, _ = decoder.raw_decode(cleaned)
            article["keyword"] = title

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

def _wrap_by_pixel_width(draw, text: str, font, max_width: int) -> list:
    words = text.split(" ")
    lines = []
    current = ""

    def width_of(s):
        bbox = draw.textbbox((0, 0), s, font=font)
        return bbox[2] - bbox[0]

    for word in words:
        candidate = f"{current} {word}".strip()
        if width_of(candidate) <= max_width or not current:
            if width_of(candidate) <= max_width:
                current = candidate
                continue
            chunk = ""
            for ch in word:
                if width_of(chunk + ch) <= max_width:
                    chunk += ch
                else:
                    if chunk:
                        lines.append(chunk)
                    chunk = ch
            current = chunk
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines

def generate_thumbnail(title: str, output_path: str, theme: dict, category: str = "라이프스타일") -> None:
    img = _make_gradient_background(THUMB_SIZE, theme["gradient"]).convert("RGBA")

    seed = int(hashlib.md5(title.encode("utf-8")).hexdigest(), 16) % 100000
    illustration = _fetch_illustration(category, THUMB_SIZE, seed)
    if illustration is not None:
        img = Image.blend(img, illustration, alpha=0.10)

    draw = ImageDraw.Draw(img)
    accent_rgb = _hex_to_rgb(theme["accent"])

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

    bar_h = 18
    draw.rectangle([(0, THUMB_SIZE[1] - bar_h), (THUMB_SIZE[0], THUMB_SIZE[1])], fill=accent_rgb + (255,))

    max_text_width = THUMB_SIZE[1] - 100
    max_text_height = int(THUMB_SIZE[1] * 0.55)

    font_size = 72
    lines, font = [], None
    while font_size >= 28:
        font = _load_font(font_size)
        lines = _wrap_by_pixel_width(draw, title, font, max_text_width)[:3]

        heights = [draw.textbbox((0, 0), line, font=font)[3] - draw.textbbox((0, 0), line, font=font)[1] for line in lines]
        total_h = sum(heights) + (len(lines) - 1) * 20
        full_wrap_count = len(_wrap_by_pixel_width(draw, title, font, max_text_width))

        if total_h <= max_text_height and full_wrap_count <= 3:
            break
        font_size -= 4

    if len(_wrap_by_pixel_width(draw, title, font, max_text_width)) > 3:
        last = lines[-1]
        while draw.textbbox((0, 0), last + "...", font=font)[2] > max_text_width and len(last) > 1:
            last = last[:-1]
        lines[-1] = last.rstrip(".,!? ") + "..."

    y = (THUMB_SIZE[1] - total_h) / 2 + 20

    for line, lh in zip(lines, heights):
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (THUMB_SIZE[0] - (bbox[2] - bbox[0])) / 2
        draw.text((x + 4, y + 4), line, font=font, fill=(0, 0, 0, 160))
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))
        y += lh + 20

    img.convert("RGB").save(output_path, format="WEBP", quality=82, method=6)

BRAND_GRADIENT = [(15, 23, 42), (30, 41, 59), (51, 65, 85)]
BRAND_ACCENT = (250, 204, 21)

LOGO_SIZE = (512, 512)
BANNER_SIZE = (1600, 420)

def generate_site_logo(output_path: str) -> None:
    img = _make_gradient_background(LOGO_SIZE, BRAND_GRADIENT).convert("RGBA")
    draw = ImageDraw.Draw(img)
    w, h = LOGO_SIZE

    margin = 36
    draw.ellipse([margin, margin, w - margin, h - margin], outline=BRAND_ACCENT + (255,), width=10)

    initial = (SITE_TITLE.strip()[:1] or "B")
    font = _load_font(220)
    bbox = draw.textbbox((0, 0), initial, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((w - tw) / 2 - bbox[0], (h - th) / 2 - bbox[1]), initial, font=font, fill=(255, 255, 255, 255))

    img.convert("RGB").save(output_path, format="WEBP", quality=90)

def generate_site_banner(output_path: str) -> None:
    img = _make_gradient_background(BANNER_SIZE, BRAND_GRADIENT).convert("RGBA")
    draw = ImageDraw.Draw(img)
    w, h = BANNER_SIZE

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
    os.makedirs(DOCS_DIR, exist_ok=True)
    logo_path = os.path.join(DOCS_DIR, "logo.webp")
    generate_site_logo(logo_path)
    generate_site_banner(os.path.join(DOCS_DIR, "banner.webp"))

    favicon_path = os.path.join(DOCS_DIR, "favicon.png")
    with Image.open(logo_path) as im:
        im.convert("RGB").resize((64, 64)).save(favicon_path, format="PNG")

def _coupang_deeplink(search_url: str):
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
    score = 0.0
    if candidate.get("category") == article.get("category", "라이프스타일"):
        score += 3.0

    current_words = set(re.findall(r"[\w가-힣]+", (article.get("title", "") + " " + article.get("keyword", ""))))
    candidate_words = set(re.findall(r"[\w가-힣]+", candidate.get("title", "")))
    overlap = len(current_words & candidate_words)
    score += overlap * 1.5

    return score

def add_internal_link(article: dict) -> dict:
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
    ad_html = _manual_ad_unit()
    if not ad_html:
        return article

    # [버그 수정]: 본문 중간 이미지 코드 삽입 후 첫 H2 바로 직전에 들어가도록 안전 검색
    idx = article["html_body"].find("<h2")
    if idx != -1:
        article["html_body"] = article["html_body"][:idx] + ad_html + article["html_body"][idx:]
    else:
        article["html_body"] += ad_html
    return article

def _fetch_content_photo(category: str, seed: int, size=(1000, 560)):
    base_prompt = ILLUSTRATION_PROMPTS.get(category, ILLUSTRATION_PROMPTS["라이프스타일"])
    prompt = base_prompt.replace("flat vector illustration of", "photo illustration of") + ", high quality, natural lighting"
    url = (
        f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}"
        f"?width={size[0]}&height={size[1]}&seed={seed}&nologo=true"
    )
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
        if img.size != size:
            img = img.resize(size)
        return img
    except Exception as e:
        print(f"  → [본문 이미지] 생성 실패, 삽입 건너뜀: {e}")
        return None

def insert_content_image(article: dict, slug: str) -> dict:
    category = article.get("category", "라이프스타일")
    seed = int(hashlib.md5((article["title"] + "-inline").encode("utf-8")).hexdigest(), 16) % 100000
    photo = _fetch_content_photo(category, seed)
    if photo is None:
        return article

    filename = f"{slug}-inline.webp"
    path = os.path.join(DOCS_DIR, "thumbs", filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    photo.save(path, format="WEBP", quality=82, method=6)

    img_html = (
        f'<img src="../thumbs/{filename}" alt="{article["title"]} 관련 이미지" loading="lazy" '
        'style="width:100%;border-radius:10px;margin:20px 0;">'
    )
    idx = article["html_body"].find("</h2>")
    if idx != -1:
        insert_at = idx + len("</h2>")
        article["html_body"] = article["html_body"][:insert_at] + img_html + article["html_body"][insert_at:]
    else:
        article["html_body"] = img_html + article["html_body"]
    return article

def add_coupang_markup(article: dict) -> dict:
    product_keyword = (article.get("product_keyword") or "").strip()
    if not product_keyword:
        print("  → 마크업 링크: 이 주제는 상품과 관련이 없어 추천 섹션을 생략합니다.")
        return article

    search_url = f"https://www.coupang.com/np/search?q={urllib.parse.quote(product_keyword)}"
    if COUPANG_PARTNER_TAG:
        search_url += f"&lptag={COUPANG_PARTNER_TAG}"

    link = _coupang_deeplink(search_url) or search_url
    link_type = "쿠팡파트너스 딥링크" if link != search_url else "일반 검색 링크"
    print(f"  → 마크업 링크 방식: {link_type} (검색어: {product_keyword})")

    extra_html = (
        f'<h2>관련 추천 상품</h2>'
        f'<p><a href="{link}" target="_blank" rel="nofollow sponsored">{product_keyword} 관련 인기 상품 보러가기</a></p>'
        '<p style="font-size:0.85em;color:#888;">이 포스팅은 쿠팡 파트너스 활동의 일환으로, '
        '이에 따른 일정액의 수수료를 제공받습니다.</p>'
    )
    article["html_body"] += extra_html
    return article

def _font_family_name(font_param: str) -> str:
    return font_param.split(":")[0].replace("+", " ")

def _build_post_nav_html() -> str:
    prev_post = None
    if os.path.exists(POSTS_JSON):
        with open(POSTS_JSON, "r", encoding="utf-8") as f:
            posts = json.load(f)
        if posts:
            prev_post = posts[0]

    prev_html = (
        f'<a href="../{prev_post["file"]}"><img src="../{prev_post["thumb"]}" alt="이전 게시물">'
        f'<span>← 이전 게시물: {prev_post["title"]}</span></a>'
        if prev_post else
        '<a href="../index.html"><span class="nav-icon">🏠</span><span>목록으로</span></a>'
    )
    latest_html = '<a href="../index.html"><span class="nav-icon">📰</span><span>최신 게시물 보기</span></a>'

    return f'<div class="post-nav">{prev_html}{latest_html}</div>'

def _build_related_html(exclude_slug: str) -> str:
    if not os.path.exists(POSTS_JSON):
        return ""
    with open(POSTS_JSON, "r", encoding="utf-8") as f:
        posts = json.load(f)
    posts = [p for p in posts if p.get("file") != exclude_slug][:3]
    if not posts:
        return ""

    # [버그 수정]: posts/ 구조 내부에서 서빙될 때 엑박 방지를 위해 경로 앞에 ../ 추가
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

    article = insert_content_image(article, slug)
    article["html_body"] += build_faq_section_html(article, theme["accent"])

    post_url = f"{SITE_URL}/posts/{post_filename}" if SITE_URL else f"posts/{post_filename}"
    thumb_url = f"{SITE_URL}/thumbs/{thumb_filename}" if SITE_URL else f"../thumbs/{thumb_filename}"

    title = article["title"]
    meta_description = article.get("meta_description", "")
    json_ld = build_json_ld(article, post_url, thumb_url, today)
    related_html = _build_related_html(exclude_slug=f"posts/{post_filename}")
    post_nav = _build_post_nav_html()
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
        post_nav=post_nav,
        decor_html=decor_html,
        bottom_ad=_manual_ad_unit(),
        search_console_meta=_search_console_meta(),
        translate_widget=_translate_widget(),
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
            translate_widget=_translate_widget(),
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
            continue
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
    if not SITE_URL:
        print("  → [SEO] SITE_URL이 설정되지 않아 sitemap.xml/robots.txt 생성을 건너뜁니다.")
        return

    url_entries = "\n".join(f"<url><loc>{SITE_URL}/{p['file']}</loc></url>" for p in posts)
    with open(os.path.join(DOCS_DIR, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write(SITEMAP_TEMPLATE.format(site_url=SITE_URL, url_entries=url_entries))

    with open(os.path.join(DOCS_DIR, "robots.txt"), "w", encoding="utf-8") as f:
        f.write(ROBOTS_TXT.format(site_url=SITE_URL))

def _blogger_configured() -> bool:
    return bool(BLOGGER_BLOG_ID and GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and GOOGLE_REFRESH_TOKEN)

def _get_blogger_access_token() -> str:
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
    if SITE_URL:
        html_body = html_body.replace('href="../posts/', f'href="{SITE_URL}/posts/')
        html_body = html_body.replace('href="../thumbs/', f'href="{SITE_URL}/thumbs/')
        html_body = html_body.replace('src="../thumbs/', f'src="{SITE_URL}/thumbs/')
    else:
        html_body = re.sub(r'<a href="\.\./(posts|thumbs)/[^"]*"[^>]*>(.*?)</a>', r"\2", html_body)
        html_body = re.sub(r'<img src="\.\./thumbs/[^"]*"[^>]*>', "", html_body)
    return html_body

def publish_to_blogger(article: dict, canonical_url: str, thumb_url: str, local_thumb_path: str) -> None:
    if not _blogger_configured():
        print("  → [블로거] 관련 Secrets가 없어 건너뜁니다 (GitHub Pages만 발행).")
        return

    try:
        access_token = _get_blogger_access_token()
        theme = get_theme(article.get("category", "라이프스타일"))
        today = datetime.now().strftime("%Y-%m-%d")
        blogger_json_ld = build_json_ld(article, canonical_url, thumb_url, today, platform="blogger")

        try:
            with open(local_thumb_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("ascii")
            img_src = f"data:image/webp;base64,{img_b64}"
        except Exception as e:
            print(f"  → [블로거] 썸네일 base64 인코딩 실패, 외부 링크로 대체: {e}")
            img_src = thumb_url

        content_html = (
            f'{_translate_widget()}'
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
