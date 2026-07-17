# -*- coding: utf-8 -*-
"""
GitHub Actions 위에서 실행되는 자동 블로그 파이프라인 스크립트 (v4 - 리스트 큐 완벽 대응 버전)
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
    "font.ttf",  # 워크플로에서 직접 다운로드하는 나눔고딕 (기본 방식)
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",  # apt로 설치했을 경우 대비(하위 호환)
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
12. 이 글이 여러 구체적인 상품·브랜드·모델을 비교하거나 소개하는 성격이면(예: "무선 이어폰 추천",
    "OO 브랜드 총정리" 등), 그 각각을 "product_list"에 {"name": "상품/브랜드명", "description": "1문장 설명"}
    형태로 채운다 (최대 6개). 이때 본문(html_body)에는 이 목록을 별도 불릿/표로 다시 나열하지 않는다
    (product_list로 아이콘과 함께 자동 렌더링됨). 비교·소개형 글이 아니면 빈 배열로 둔다.
13. 출력은 반드시 아래 JSON 형식만 반환한다. 다른 설명, 코드블록 기호(```) 없이 순수 JSON만 출력한다:
{
  "title": "...",
  "html_body": "...",
  "meta_description": "...",
  "schema_type": "Article 또는 FAQPage 또는 HowTo",
  "faq_items": [{"question": "...", "answer": "..."}],
  "howto_steps": [{"name": "...", "text": "..."}],
  "category": "위 10개 중 하나",
  "product_keyword": "쇼핑 키워드 또는 빈 문자열",
  "product_list": [{"name": "...", "description": "..."}]
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
    "뷰티패션": "minimalist pencil sketch style illustration of cosmetics lipstick and fashion clothing items, clean line art",
    "푸드맛집": "minimalist pencil sketch style illustration of food dishes and cafe coffee items, clean line art",
    "여행": "minimalist pencil sketch style illustration of travel landscape airplane suitcase palm tree, clean line art",
    "테크IT": "minimalist pencil sketch style illustration of laptop computer and technology icons, clean modern line art",
    "재테크머니": "minimalist pencil sketch style illustration of coins money and finance growth chart, clean line art",
    "헬스운동": "minimalist pencil sketch style illustration of fitness workout dumbbell and healthy food, clean line art",
    "홈인테리어": "minimalist pencil sketch style illustration of cozy home interior furniture and plants, clean line art",
    "대출보험": "minimalist pencil sketch style illustration of bank building document and contract, clean professional line art",
    "정부지원금": "minimalist pencil sketch style illustration of government building document and checklist, clean line art",
    "라이프스타일": "minimalist pencil sketch style illustration of coffee book and cozy lifestyle items, clean line art",
}
ILLUSTRATION_SUFFIX = ", simple outline shapes, white background, isolated black or monochromatic vector lines, no watermark, no text"

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
ENABLE_TTS = os.environ.get("ENABLE_TTS", "true").strip().lower() != "false"

def _build_tts_widget(accent: str, content_selector: str = ".content") -> str:
    if not ENABLE_TTS:
        return ""
    return f"""
<div style="position:fixed;bottom:20px;right:20px;z-index:998;">
  <button id="tts-btn" type="button" onclick="window.__ttsToggle && window.__ttsToggle();"
    style="border:none;border-radius:999px;background:{accent};color:#fff;font-weight:700;
    font-size:13px;padding:10px 16px;box-shadow:0 3px 12px rgba(0,0,0,0.28);cursor:pointer;">듣기</button>
</div>
<script>
(function() {{
  var speaking = false;
  var currentAudio = null;
  var chunkQueue = [];
  var chunkIndex = 0;
  var TTS_ENDPOINT = '[https://api.streamelements.com/kappa/v2/speech?voice=Seoyeon&text=](https://api.streamelements.com/kappa/v2/speech?voice=Seoyeon&text=)';

  function updateBtn() {{
    var btn = document.getElementById('tts-btn');
    if (btn) btn.textContent = speaking ? '정지' : '듣기';
  }}

  function extractReadableText() {{
    var content = document.querySelector('{content_selector}');
    if (!content) return '';
    var clone = content.cloneNode(true);
    var strip = clone.querySelectorAll('table, button, script, style, .related, [id^="tblzoom"]');
    strip.forEach(function(el) {{ el.remove(); }});
    return (clone.innerText || clone.textContent || '').trim();
  }}

  function splitIntoChunks(text, maxLen) {{
    var chunks = [];
    while (text.length > 0) {{
      var piece = text.slice(0, maxLen);
      if (text.length > maxLen) {{
        var cut = Math.max(piece.lastIndexOf('.'), piece.lastIndexOf('\\n'), piece.lastIndexOf('!'), piece.lastIndexOf('?'));
        if (cut > 40) piece = text.slice(0, cut + 1);
      }}
      chunks.push(piece);
      text = text.slice(piece.length);
    }}
    return chunks.slice(0, 20);
  }}

  function stop() {{
    speaking = false;
    if (currentAudio) {{ currentAudio.pause(); currentAudio = null; }}
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    updateBtn();
  }}

  function playChunkWithAI(i) {{
    if (!speaking || i >= chunkQueue.length) {{ speaking = false; updateBtn(); return; }}
    var audio = new Audio(TTS_ENDPOINT + encodeURIComponent(chunkQueue[i]));
    currentAudio = audio;
    audio.onended = function() {{ playChunkWithAI(i + 1); }};
    audio.onerror = function() {{ speakWithBrowserVoice(chunkQueue.join(' ')); }};
    audio.play().catch(function() {{ speakWithBrowserVoice(chunkQueue.join(' ')); }});
  }}

  function speakWithBrowserVoice(text) {{
    var synth = window.speechSynthesis;
    if (!synth) {{ speaking = false; updateBtn(); return; }}
    var voices = synth.getVoices() || [];
    var ko = voices.filter(function(v) {{ return v.lang && v.lang.toLowerCase().indexOf('ko') === 0; }});
    var female = ko.filter(function(v) {{ return /female|여성|유나|보라|서연|지민/i.test(v.name); }});
    var utter = new SpeechSynthesisUtterance(text.slice(0, 3000));
    var voice = female[0] || ko[0];
    if (voice) utter.voice = voice;
    utter.lang = 'ko-KR';
    utter.rate = 0.92;
    utter.onend = function() {{ speaking = false; updateBtn(); }};
    utter.onerror = function() {{ speaking = false; updateBtn(); }};
    synth.cancel();
    synth.speak(utter);
  }}

  window.__ttsToggle = function() {{
    if (speaking) {{ stop(); }} else {{ speak(); }}
  }};

  setTimeout(function() {{
    try {{ speak(); }} catch (e) {{}}
  }}, 1000);
}})();
</script>"""

def _translate_widget() -> str:
    if not ENABLE_AUTO_TRANSLATE:
        return ""
    return """
<div style="position:fixed;top:10px;right:10px;z-index:999;">
  <button onclick="var e=document.getElementById('gt-box');e.style.display=(e.style.display==='none'||!e.style.display)?'block':'none';'
    style="border:none;border-radius:999px;background:#fff;color:#333;font-weight:700;font-size:12px;
    padding:9px 14px;box-shadow:0 2px 8px rgba(0,0,0,0.25);cursor:pointer;">번역</button>
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
    if not article.get("faq_items"):
        return ""

    cards = []
    for i, qa in enumerate(article["faq_items"], 1):
        question = qa.get("question", "")
        answer = qa.get("answer", "")
        cards.append(
            f'<details style="margin:14px 0;background:#f7f8fa;border-left:4px solid {accent};'
            'border-radius:8px;padding:2px 18px;" open>'
            '<summary style="cursor:pointer;padding:14px 0;font-family:\'Noto Sans KR\',-apple-system,sans-serif;'
            f'font-weight:800;font-size:1.08em;color:#111;outline:none;user-select:none;">Q{i}. {question}</summary>'
            '<p style="margin:0;padding:0 0 16px;font-family:\'Noto Sans KR\',-apple-system,sans-serif;'
            f'font-weight:400;color:#555;line-height:1.75;">A. {answer}</p>'
            '</details>'
        )

    return (
        '<h2 style="margin-top:2em;">자주 묻는 질문(FAQ) <span style="font-size:0.6em;color:#999;font-weight:400;">'
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
    graph_nodes = [data, breadcrumb]

    products = article.get("product_list") or []
    if products:
        graph_nodes.append({
            "@type": "ItemList",
            "name": f"{title} - 소개된 상품 목록",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": i,
                    "item": {"@type": "Product", "name": p.get("name", ""), "description": p.get("description", "")},
                }
                for i, p in enumerate(products[:6], 1)
            ],
        })
        print(f"  → [스키마 마크업] ItemList 추가 (상품 {len(products[:6])}개)")

    graph_data = {"@context": "[https://schema.org](https://schema.org)", "@graph": graph_nodes}
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
  table {{ width: 100%; min-width: 460px; border-collapse: collapse; font-size: 0.92em; }}
  th, td {{ padding: 11px 14px; border-bottom: 1px solid #eee; text-align: left; line-height: 1.5; }}
  th {{ background: {accent}14; font-weight: 800; color: #111; white-space: nowrap; }}
  tr:last-child td {{ border-bottom: none; }}
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

  details summary {{ list-style: none; display: flex; align-items: center; justify-content: space-between; gap: 10px; }}
  details summary::-webkit-details-marker {{ display: none; }}
  details summary::after {{ content: '▼'; font-size: 0.75em; color: {accent}; flex-shrink: 0; }}
  details[open] summary::after {{ content: '▲'; }}
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
{tts_widget}
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


# =====================================================================
# [핵심 변경] 리스트 포맷 대기열 파일 대응 get_title_from_args_or_queue
# =====================================================================
def get_title_from_args_or_queue() -> str:
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return sys.argv[1].strip()

    if not os.path.exists(QUEUE_FILE):
        raise RuntimeError(f"{QUEUE_FILE} 이 없습니다. 저장소 루트에 큐 파일을 만들어주세요.")

    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
        queue = json.load(f)

    # 딕셔너리 구조가 아닌 순수 리스트 구조에 대한 검증 및 처리 수행
    if not isinstance(queue, list):
        raise TypeError(f"{QUEUE_FILE}의 구조가 딕셔너리가 아닌 '리스트' 형식(예: ['A', 'B'])이어야 합니다. 현재 형태: {type(queue)}")

    if not queue:
        raise RuntimeError("대기 중인 키워드가 없습니다. keywords_queue.json의 리스트를 채워주세요.")

    # 첫 번째 요소를 안전하게 꺼내고 대기열에서 제거
    title = queue.pop(0)

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
            cleaned = text.strip().removeprefix("

