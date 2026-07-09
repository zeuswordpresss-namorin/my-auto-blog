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

import hashlib
import hmac
import io
import json
import os
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
SITE_URL = os.environ.get("SITE_URL", "").rstrip("/")  # 예: https://아이디.github.io/my-auto-blog
GA_MEASUREMENT_ID = os.environ.get("GA_MEASUREMENT_ID", "")  # 예: G-XXXXXXXXXX
ADSENSE_CLIENT_ID = os.environ.get("ADSENSE_CLIENT_ID", "")  # 예: ca-pub-1234567890123456

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
1. 제목은 검색 의도를 반영하되 과장/낚시성 표현은 피한다.
2. 소제목(H2)을 4~6개 사용해 구조화한다.
3. 확인되지 않은 구체적 수치·통계를 지어내지 않는다.
4. 글자 수는 1500~2200자 내외.
5. 자연스러운 위치에 제품 추천 문맥을 1곳 만든다 (실제 링크는 넣지 않음).
6. 콘텐츠 내용을 보고 아래 3가지 중 구글 상위노출에 가장 유리한 스키마 타입을 스스로 판단해서 고른다:
   - "FAQPage": 자주 묻는 질문/답변 형태로 정리하기 좋은 주제일 때 (예: "~란?", "~ 방법", "~ 차이" 등 질의응답형 검색의도)
   - "HowTo": 순서가 있는 절차/방법을 안내하는 주제일 때 (예: "~하는 법", "~ 설치 방법")
   - "Article": 위 둘에 해당하지 않는 일반 정보/추천/리뷰형 글일 때
7. 고른 스키마 타입에 맞는 데이터를 함께 채운다:
   - FAQPage를 골랐다면 "faq_items"에 실제 본문 내용과 일치하는 질문/답변 3~5개를 넣는다 (본문에도 자연스럽게 Q&A 형태로 녹여쓴다)
   - HowTo를 골랐다면 "howto_steps"에 실제 본문 순서와 일치하는 단계 3~6개를 넣는다 (각 step은 name(단계 제목)과 text(설명))
   - Article이면 faq_items, howto_steps는 빈 배열로 둔다
8. 제목/키워드를 보고 아래 카테고리 중 가장 알맞은 것 하나를 "category"에 고른다 (디자인 테마 자동 매칭용):
   ["뷰티패션", "푸드맛집", "여행", "테크IT", "재테크머니", "헬스운동", "홈인테리어", "라이프스타일"]
   애매하면 "라이프스타일"을 선택한다.
9. 출력은 반드시 아래 JSON 형식만 반환한다. 다른 설명, 코드블록 기호(```) 없이 순수 JSON만 출력한다:
{
  "title": "...",
  "html_body": "...",
  "meta_description": "...",
  "schema_type": "Article 또는 FAQPage 또는 HowTo",
  "faq_items": [{"question": "...", "answer": "..."}],
  "howto_steps": [{"name": "...", "text": "..."}],
  "category": "위 8개 중 하나"
}
html_body는 <h2>, <p>, <ul> 등을 사용한 HTML 조각이어야 한다."""


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
    },
    "푸드맛집": {
        "gradient": [(255, 107, 53), (247, 147, 30), (255, 210, 63)],
        "accent": "#ff6b35",
        "badge": "🍽️ 푸드·맛집",
        "label": "FOOD",
        "font": "Jua",
    },
    "여행": {
        "gradient": [(17, 153, 142), (56, 239, 125), (100, 210, 255)],
        "accent": "#11998e",
        "badge": "✈️ 여행",
        "label": "TRAVEL",
        "font": "Gowun+Dodum",
    },
    "테크IT": {
        "gradient": [(30, 60, 114), (42, 82, 152), (0, 198, 255)],
        "accent": "#2a5298",
        "badge": "💻 테크·IT",
        "label": "TECH",
        "font": "Noto+Sans+KR:wght@700",
    },
    "재테크머니": {
        "gradient": [(17, 105, 79), (56, 173, 118), (168, 224, 99)],
        "accent": "#11694f",
        "badge": "💰 재테크",
        "label": "MONEY",
        "font": "Noto+Sans+KR:wght@700",
    },
    "헬스운동": {
        "gradient": [(19, 78, 94), (113, 178, 128), (168, 224, 99)],
        "accent": "#134e5e",
        "badge": "💪 헬스·운동",
        "label": "FITNESS",
        "font": "Jua",
    },
    "홈인테리어": {
        "gradient": [(196, 132, 88), (218, 170, 122), (238, 210, 175)],
        "accent": "#c48458",
        "badge": "🏠 홈·인테리어",
        "label": "HOME",
        "font": "Gowun+Dodum",
    },
    "라이프스타일": {
        "gradient": [(66, 133, 244), (156, 39, 176), (234, 67, 121)],
        "accent": "#4a90d9",
        "badge": "✨ 라이프스타일",
        "label": "LIFESTYLE",
        "font": "Noto+Sans+KR:wght@700",
    },
}
DEFAULT_THEME = CATEGORY_THEMES["라이프스타일"]


def get_theme(category: str) -> dict:
    return CATEGORY_THEMES.get(category, DEFAULT_THEME)


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


def build_json_ld(article: dict, canonical_url: str, thumb_url: str, date: str) -> str:
    """AI가 고른 스키마 타입(schema_type)에 맞춰 JSON-LD 구조화 데이터를 만듭니다."""
    schema_type = article.get("schema_type", "Article")
    title = article["title"]
    meta_description = article.get("meta_description", "")

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
        schema_type = "Article"
        data = {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": title,
            "description": meta_description,
            "image": thumb_url,
            "datePublished": date,
            "author": {"@type": "Organization", "name": SITE_TITLE},
        }

    print(f"  → [스키마 마크업] AI가 선택한 타입: {schema_type}")
    return json.dumps(data, ensure_ascii=False, indent=2)


POST_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<meta name="description" content="{meta_description}">
<link rel="canonical" href="{canonical_url}">
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
  body {{ max-width: 720px; margin: 0 auto; padding: 0 20px 60px; font-family: 'Noto Sans KR', -apple-system, sans-serif; line-height: 1.75; color: #1a1a1a; background: #fafafa; }}
  .hero {{ margin: 0 -20px 24px; position: relative; }}
  .hero img {{ width: 100%; aspect-ratio: 16/9; object-fit: cover; display: block; }}
  .badge {{ display: inline-block; background: {accent}; color: #fff; font-size: 0.8em; font-weight: 700; padding: 5px 14px; border-radius: 999px; margin: 20px 0 10px; }}
  h1 {{ font-family: '{font_family}', 'Noto Sans KR', sans-serif; font-size: 1.9em; line-height: 1.35; margin: 0 0 8px; }}
  h2 {{ font-family: '{font_family}', 'Noto Sans KR', sans-serif; font-size: 1.35em; margin-top: 2em; padding: 10px 14px; background: linear-gradient(90deg, {accent}22, transparent); border-left: 5px solid {accent}; border-radius: 4px; }}
  p {{ margin: 1em 0; }}
  a.back {{ display: inline-block; margin: 20px 0; color: {accent}; text-decoration: none; font-weight: 700; }}
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
<a class="back" href="../index.html">← 목록으로</a>
<div class="hero"><img src="../thumbs/{thumb_filename}" alt="{title}"></div>
<span class="badge">{badge}</span>
<h1>{title}</h1>
<p class="meta">{date}</p>
{html_body}
{related_html}
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
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="{fonts_url}" rel="stylesheet">{ga_snippet}{adsense_snippet}
<style>
  * {{ box-sizing: border-box; }}
  body {{ max-width: 1000px; margin: 0 auto; padding: 30px 20px 60px; font-family: 'Noto Sans KR', -apple-system, sans-serif; background:#f5f5f7; color:#1a1a1a; }}
  h1.site-title {{ font-family: 'Jua', sans-serif; font-size: 2em; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom: 6px; }}
  .dash-link {{ font-size: 0.4em; color:#888; text-decoration:none; background:#eee; padding:6px 14px; border-radius:999px; }}
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
</style>
</head>
<body>
<h1 class="site-title">{site_title} <a class="dash-link" href="dashboard.html">📊 성과관리</a></h1>

{hero_html}
{mid_html}
{bottom_html}
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


def generate_thumbnail(title: str, output_path: str, theme: dict) -> None:
    img = _make_gradient_background(THUMB_SIZE, theme["gradient"])
    draw = ImageDraw.Draw(img, "RGBA")
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

    img.convert("RGB").save(output_path, quality=90)


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
        f'<a class="related-card" href="../{p["file"]}"><img src="../{p["thumb"]}" alt="{p["title"]}">'
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
    thumb_filename = f"{slug}-{today}.jpg"
    post_filename = f"{slug}-{today}.html"

    generate_thumbnail(article["title"], os.path.join(DOCS_DIR, "thumbs", thumb_filename), theme)

    post_url = f"{SITE_URL}/posts/{post_filename}" if SITE_URL else f"posts/{post_filename}"
    thumb_url = f"{SITE_URL}/thumbs/{thumb_filename}" if SITE_URL else f"../thumbs/{thumb_filename}"

    title = article["title"]
    meta_description = article.get("meta_description", "")
    json_ld = build_json_ld(article, post_url, thumb_url, today)
    related_html = _build_related_html(exclude_slug=f"posts/{post_filename}")

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
    return post_meta, json_ld, thumb_url


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
            f'<a class="hero" href="{p["file"]}"><img src="{p["thumb"]}" alt="{p["title"]}">'
            f'<div class="hero-body"><span class="hero-badge" style="background:{p.get("accent", "#4a90d9")}">'
            f'{p.get("badge", "✨ 라이프스타일")}</span>'
            f'<div class="hero-title">{p["title"]}</div>'
            f'<div class="date">{p["date"]}</div></div></a>'
        )

    mid_html = ""
    if mid_posts:
        cards = "\n".join(
            f'<a class="mid-card" href="{p["file"]}"><img src="{p["thumb"]}" alt="{p["title"]}">'
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
            f'<a class="bottom-card" href="{p["file"]}"><img src="{p["thumb"]}" alt="{p["title"]}">'
            f'<div class="bottom-body"><span class="badge-sm" style="background:{p.get("accent", "#4a90d9")}">'
            f'{p.get("badge", "✨ 라이프스타일")}</span>'
            f'<div class="bottom-title">{p["title"]}</div></div></a>'
            for p in bottom_posts
        )
        bottom_html = f'<div class="tier-label">🗂️ 지난 글 모아보기</div><div class="bottom-grid">{cards}</div>'

    with open(os.path.join(DOCS_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(INDEX_TEMPLATE.format(
            site_title=SITE_TITLE,
            site_url=SITE_URL or ".", ga_snippet=_ga_snippet(),
            adsense_snippet=_adsense_snippet(),
            fonts_url=_google_fonts_url(),
            hero_html=hero_html, mid_html=mid_html, bottom_html=bottom_html,
        ))

    return posts


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


def publish_to_blogger(article: dict, json_ld: str, thumb_url: str) -> None:
    """같은 글을 구글 블로거에도 발행합니다. 미설정/실패해도 전체 파이프라인은 계속 진행됩니다."""
    if not _blogger_configured():
        print("  → [블로거] 관련 Secrets가 없어 건너뜁니다 (GitHub Pages만 발행).")
        return
    if not SITE_URL:
        print("  → [블로거] 주의: SITE_URL이 없어 썸네일 이미지가 블로거에서 깨질 수 있습니다 (Variables에 SITE_URL 등록 권장).")

    try:
        access_token = _get_blogger_access_token()
        theme = get_theme(article.get("category", "라이프스타일"))

        # 스키마 마크업(JSON-LD)을 본문 안에 함께 삽입 (대부분의 블로거 테마에서 script 태그 유지됨)
        content_html = (
            f'<img src="{thumb_url}" style="max-width:100%;border-radius:8px;" alt="{article["title"]}">'
            f'<span style="display:inline-block;background:{theme["accent"]};color:#fff;font-size:0.85em;'
            f'font-weight:bold;padding:4px 12px;border-radius:999px;margin:14px 0 4px;">{theme["badge"]}</span>'
            f'{article["html_body"]}'
            f'<script type="application/ld+json">{json_ld}</script>'
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


def run():
    title = get_title_from_args_or_queue()
    print(f"[처리 시작] 제목: {title}")

    article = generate_article(title)
    print(f"  → 글 생성 완료: {article['title']}")

    article = add_coupang_markup(article)
    post_meta, json_ld, thumb_url = save_post(article)
    posts = update_index(post_meta)
    update_dashboard(posts)
    update_seo_files(posts)
    publish_to_blogger(article, json_ld, thumb_url)

    print(f"  → 저장 완료: docs/{post_meta['file']}, docs/{post_meta['thumb']}")
    print(f"  → 대시보드/사이트맵 갱신 완료")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        print(f"[오류] {e}")
        sys.exit(1)

