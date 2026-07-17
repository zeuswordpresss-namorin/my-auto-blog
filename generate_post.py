# -*- coding: utf-8 -*-
"""
GitHub Actions 위에서 실행되는 자동 블로그 파이프라인 스크립트

v4 업그레이드:
  - Gemini 재시도: 5회, 쿨타임 10/20/30/45/60초 단계적 대기
  - 타임아웃/연결 오류도 동일 쿨타임 재시도 적용
  - 구글 블로거 동시 발행 통합
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
# 환경변수 설정
# =====================================================================
GEMINI_API_KEY        = os.environ.get("GEMINI_API_KEY", "")
SITE_TITLE            = os.environ.get("SITE_TITLE", "내 자동 블로그")
SITE_TAGLINE          = os.environ.get("SITE_TAGLINE", "매일 자동으로 업데이트되는 정보 큐레이션 블로그")
SITE_URL              = os.environ.get("SITE_URL", "").rstrip("/")
GA_MEASUREMENT_ID     = os.environ.get("GA_MEASUREMENT_ID", "")
GOOGLE_SITE_VERIFICATION = os.environ.get("GOOGLE_SITE_VERIFICATION", "")
ADSENSE_CLIENT_ID     = os.environ.get("ADSENSE_CLIENT_ID", "")
ADSENSE_SLOT_ID       = os.environ.get("ADSENSE_SLOT_ID", "")
COUPANG_PARTNER_TAG   = os.environ.get("COUPANG_PARTNER_TAG", "")
COUPANG_ACCESS_KEY    = os.environ.get("COUPANG_ACCESS_KEY", "")
COUPANG_SECRET_KEY    = os.environ.get("COUPANG_SECRET_KEY", "")
BLOGGER_BLOG_ID       = os.environ.get("BLOGGER_BLOG_ID", "")
GOOGLE_CLIENT_ID      = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET  = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REFRESH_TOKEN  = os.environ.get("GOOGLE_REFRESH_TOKEN", "")
ENABLE_AUTO_TRANSLATE = os.environ.get("ENABLE_AUTO_TRANSLATE", "true").strip().lower() != "false"
ENABLE_TTS            = os.environ.get("ENABLE_TTS", "true").strip().lower() != "false"

FONT_CANDIDATES = [
    "font.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
]

DOCS_DIR   = "docs"
POSTS_DIR  = os.path.join(DOCS_DIR, "posts")
POSTS_JSON = os.path.join(DOCS_DIR, "posts.json")
QUEUE_FILE = "keywords_queue.json"

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash:generateContent?key={api_key}"
)

# Gemini 재시도 설정 -- 5회, 각 실패 후 10->20->30->45->60 초 대기
GEMINI_MAX_RETRIES  = 5
GEMINI_RETRY_WAITS  = [10, 20, 30, 45, 60]
GEMINI_RETRY_STATUS = {429, 500, 503}

# =====================================================================
# AI 프롬프트
# =====================================================================
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
   쇼핑 키워드(2~4단어)를 넣는다. 예: 육아 관련 글 -> "신생아 용품 세트", 게임 패치 소식 -> "게이밍 마우스".
   연예인 뉴스, 시사/정치, 날씨 등 상품과 자연스럽게 연결되지 않는 주제라면 억지로 만들지 말고
   반드시 빈 문자열("")로 둔다 (빈 문자열이면 상품 추천 섹션 자체가 생략됨).
8. 콘텐츠 내용을 보고 아래 3가지 중 구글 상위노출에 가장 유리한 스키마 타입을 스스로 판단해서 고른다:
   - "FAQPage": 자주 묻는 질문/답변 형태로 정리하기 좋은 주제일 때
   - "HowTo": 순서가 있는 절차/방법을 안내하는 주제일 때
   - "Article": 위 둘에 해당하지 않는 일반 정보/추천/리뷰형 글일 때
9. 고른 스키마 타입에 맞는 데이터를 함께 채운다:
   - FAQPage: "faq_items"에 질문/답변 3~5개
   - HowTo: "howto_steps"에 단계 3~6개 (각 step은 name과 text)
   - Article: faq_items, howto_steps는 빈 배열
10. 제목/키워드를 보고 아래 카테고리 중 가장 알맞은 것 하나를 "category"에 고른다:
    ["뷰티패션", "푸드맛집", "여행", "테크IT", "재테크머니", "헬스운동", "홈인테리어", "대출보험", "정부지원금", "라이프스타일"]
    애매하면 "라이프스타일"을 선택한다.
11. category가 "대출보험" 또는 "정부지원금"이면:
    - 특정 금융사·상품명을 단정적으로 추천하지 않는다
    - 신청 절차나 자격요건은 "일반적으로"라는 표현을 쓰고, 최신 여부는 공식 기관 확인이 필요하다는 점을 본문에 언급한다
12. 이 글이 여러 구체적인 상품·브랜드·모델을 비교하거나 소개하는 성격이면,
    그 각각을 "product_list"에 {"name": "상품/브랜드명", "description": "1문장 설명"} 형태로 채운다 (최대 6개).
    비교·소개형 글이 아니면 빈 배열로 둔다.
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


# =====================================================================
# 카테고리 테마
# =====================================================================
CATEGORY_THEMES = {
    "뷰티패션":    {"gradient": [(255, 107, 157), (255, 154, 158), (250, 208, 196)], "accent": "#ff6b9d", "badge": "\U0001f484 뷰티\xb7패션",    "label": "BEAUTY",    "font": "Gowun+Dodum",             "decor": ["\U0001f484", "\U0001f485", "\U0001f457", "\U0001f460", "\U0001f48b", "\U0001f380", "\U0001f48e", "\U0001f338"]},
    "푸드맛집":    {"gradient": [(255, 107,  53), (247, 147,  30), (255, 210,  63)], "accent": "#ff6b35", "badge": "\U0001f37d\ufe0f 푸드\xb7맛집",  "label": "FOOD",      "font": "Jua",                     "decor": ["\U0001f355", "\U0001f354", "\U0001f370", "\U0001f35c", "\U0001f369", "\u2615", "\U0001f353", "\U0001f9c1"]},
    "여행":        {"gradient": [( 17, 153, 142), ( 56, 239, 125), (100, 210, 255)], "accent": "#11998e", "badge": "\u2708\ufe0f 여행",              "label": "TRAVEL",    "font": "Gowun+Dodum",             "decor": ["\u2708\ufe0f", "\U0001f334", "\U0001f5fa\ufe0f", "\U0001f9f3", "\U0001f3d6\ufe0f", "\U0001f4f8", "\U0001f697", "\U0001f5fc"]},
    "테크IT":      {"gradient": [( 30,  60, 114), ( 42,  82, 152), (  0, 198, 255)], "accent": "#2a5298", "badge": "\U0001f4bb 테크\xb7IT",          "label": "TECH",      "font": "Noto+Sans+KR:wght@700",   "decor": ["\U0001f4bb", "\u2328\ufe0f", "\U0001f5a5\ufe0f", "\U0001f4f1", "\U0001f50c", "\U0001f916", "\u26a1", "\U0001f6f0\ufe0f"]},
    "재테크머니":  {"gradient": [( 17, 105,  79), ( 56, 173, 118), (168, 224,  99)], "accent": "#11694f", "badge": "\U0001f4b0 재테크",              "label": "MONEY",     "font": "Noto+Sans+KR:wght@700",   "decor": ["\U0001f4b0", "\U0001f4b5", "\U0001f4c8", "\U0001fa99", "\U0001f3e6", "\U0001f4b3", "\U0001f4ca", "\U0001f437"]},
    "헬스운동":    {"gradient": [( 19,  78,  94), (113, 178, 128), (168, 224,  99)], "accent": "#134e5e", "badge": "\U0001f4aa 헬스\xb7운동",         "label": "FITNESS",   "font": "Jua",                     "decor": ["\U0001f4aa", "\U0001f3cb\ufe0f", "\U0001f957", "\U0001f9d8", "\U0001f3c3", "\u23f1\ufe0f", "\U0001f6b4", "\U0001f951"]},
    "홈인테리어":  {"gradient": [(196, 132,  88), (218, 170, 122), (238, 210, 175)], "accent": "#c48458", "badge": "\U0001f3e0 홈\xb7인테리어",       "label": "HOME",      "font": "Gowun+Dodum",             "decor": ["\U0001f3e0", "\U0001fab4", "\U0001f56f\ufe0f", "\U0001f6cb\ufe0f", "\U0001f5bc\ufe0f", "\U0001f9fa", "\U0001fa9e", "\U0001f6cf\ufe0f"]},
    "라이프스타일":{"gradient": [( 66, 133, 244), (156,  39, 176), (234,  67, 121)], "accent": "#4a90d9", "badge": "\u2728 라이프스타일",             "label": "LIFESTYLE", "font": "Noto+Sans+KR:wght@700",   "decor": ["\u2728", "\U0001f338", "\u2615", "\U0001f4d3", "\U0001f3a7", "\U0001f54a\ufe0f", "\U0001f33f", "\u2b50"]},
    "대출보험":    {"gradient": [( 20,  30,  48), ( 36,  59,  85), ( 65,  90, 119)], "accent": "#1e3a5f", "badge": "\U0001f3e6 대출\xb7보험",         "label": "FINANCE",   "font": "Noto+Sans+KR:wght@700",   "decor": ["\U0001f3e6", "\U0001f4c4", "\U0001f4b3", "\U0001f50d", "\U0001f4de", "\u2705", "\U0001f4bc", "\U0001f9fe"], "ymyl": True},
    "정부지원금":  {"gradient": [(  0,  91,  82), (  0, 128, 105), ( 82, 183, 136)], "accent": "#00695c", "badge": "\U0001f3db\ufe0f 정부지원금",      "label": "SUPPORT",   "font": "Noto+Sans+KR:wght@700",   "decor": ["\U0001f3db\ufe0f", "\U0001f4cb", "\U0001f58a\ufe0f", "\U0001f4c5", "\u2705", "\U0001f48c", "\U0001faaa", "\U0001f4e2"], "ymyl": True},
}
DEFAULT_THEME = CATEGORY_THEMES["라이프스타일"]


def get_theme(category):
    return CATEGORY_THEMES.get(category, DEFAULT_THEME)


ILLUSTRATION_PROMPTS = {
    "뷰티패션":    "minimalist pencil sketch style illustration of cosmetics lipstick and fashion clothing items, clean line art",
    "푸드맛집":    "minimalist pencil sketch style illustration of food dishes and cafe coffee items, clean line art",
    "여행":        "minimalist pencil sketch style illustration of travel landscape airplane suitcase palm tree, clean line art",
    "테크IT":      "minimalist pencil sketch style illustration of laptop computer and technology icons, clean modern line art",
    "재테크머니":  "minimalist pencil sketch style illustration of coins money and finance growth chart, clean line art",
    "헬스운동":    "minimalist pencil sketch style illustration of fitness workout dumbbell and healthy food, clean line art",
    "홈인테리어":  "minimalist pencil sketch style illustration of cozy home interior furniture and plants, clean line art",
    "대출보험":    "minimalist pencil sketch style illustration of bank building document and contract, clean professional line art",
    "정부지원금":  "minimalist pencil sketch style illustration of government building document and checklist, clean line art",
    "라이프스타일":"minimalist pencil sketch style illustration of coffee book and cozy lifestyle items, clean line art",
}
ILLUSTRATION_SUFFIX = ", simple outline shapes, white background, isolated black or monochromatic vector lines, no watermark, no text"

THUMB_SIZE  = (1280, 720)
LOGO_SIZE   = (512, 512)
BANNER_SIZE = (1600, 420)
BRAND_GRADIENT = [(15, 23, 42), (30, 41, 59), (51, 65, 85)]
BRAND_ACCENT   = (250, 204, 21)

ALL_THEME_FONTS = sorted({t["font"] for t in CATEGORY_THEMES.values()})


# =====================================================================
# 유틸리티
# =====================================================================

def slugify(text):
    text = re.sub(r"[^\w\s-]", "", text).strip()
    return re.sub(r"[\s]+", "-", text) or "post"


def _hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def _load_font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    print("[안내] 한글 폰트를 찾지 못해 기본 폰트로 대체합니다.")
    return ImageFont.load_default()


def _font_family_name(font_param):
    return font_param.split(":")[0].replace("+", " ")


def _google_fonts_url():
    families = "&family=".join(ALL_THEME_FONTS)
    return f"https://fonts.googleapis.com/css2?family={families}&family=Noto+Sans+KR:wght@400;700;900&display=swap"


# =====================================================================
# 키워드 큐
# =====================================================================

def get_title_from_args_or_queue():
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return sys.argv[1].strip()

    if not os.path.exists(QUEUE_FILE):
        raise RuntimeError(f"{QUEUE_FILE} 이 없습니다.")

    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
        queue = json.load(f)

    pending = queue.get("pending", [])
    if not pending:
        raise RuntimeError("대기 중인 키워드가 없습니다.")

    title = pending.pop(0)
    queue.setdefault("completed", []).append(title)
    queue["pending"] = pending

    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)

    return title


# =====================================================================
# Gemini 글 생성 -- 재시도 5회, 10/20/30/45/60 초
# =====================================================================

def generate_article(title):
    """Gemini API 호출. 실패 시 최대 5회 재시도 (10/20/30/45/60 초 간격)."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY 환경변수가 비어있습니다.")

    url = GEMINI_URL.format(api_key=GEMINI_API_KEY)
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": f"제목: '{title}' 에 대한 블로그 글을 작성해주세요."}]}],
    }

    last_error = None
    for attempt in range(1, GEMINI_MAX_RETRIES + 1):
        remaining = GEMINI_MAX_RETRIES - attempt
        try:
            resp = requests.post(url, json=payload, timeout=90)

            if resp.status_code in GEMINI_RETRY_STATUS:
                wait = GEMINI_RETRY_WAITS[attempt - 1]
                last_error = f"HTTP {resp.status_code}"
                body_preview = resp.text[:200] if resp.text else "(응답 없음)"
                if remaining > 0:
                    print(f"  -> [Gemini] {last_error} | {body_preview}")
                    print(f"  -> [Gemini] {wait}초 대기 후 재시도 ({attempt}/{GEMINI_MAX_RETRIES}, 남은: {remaining}회)")
                    time.sleep(wait)
                    continue
                else:
                    raise RuntimeError(f"최대 재시도 초과. 마지막 오류: {last_error} | {body_preview}")

            resp.raise_for_status()

            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

            decoder = json.JSONDecoder()
            article, _ = decoder.raw_decode(cleaned)
            article["keyword"] = title

            desc = article.get("meta_description", "").strip()
            if len(desc) > 160:
                desc = desc[:157].rstrip() + "..."
            article["meta_description"] = desc

            print(f"  -> [Gemini] 성공 (시도 {attempt}/{GEMINI_MAX_RETRIES})")
            return article

        except (KeyError, IndexError) as e:
            raise ValueError(f"Gemini 응답 형식 오류: {e}") from e

        except json.JSONDecodeError as e:
            raise ValueError(f"JSON 파싱 실패: {e}") from e

        except requests.exceptions.Timeout as e:
            wait = GEMINI_RETRY_WAITS[attempt - 1]
            last_error = f"타임아웃"
            if remaining > 0:
                print(f"  -> [Gemini] {last_error} -- {wait}초 대기 후 재시도 ({attempt}/{GEMINI_MAX_RETRIES}, 남은: {remaining}회)")
                time.sleep(wait)
            else:
                raise RuntimeError(f"최대 재시도 초과 (타임아웃)") from e

        except requests.exceptions.ConnectionError as e:
            wait = GEMINI_RETRY_WAITS[attempt - 1]
            last_error = "연결 오류"
            if remaining > 0:
                print(f"  -> [Gemini] {last_error} -- {wait}초 대기 후 재시도 ({attempt}/{GEMINI_MAX_RETRIES}, 남은: {remaining}회)")
                time.sleep(wait)
            else:
                raise RuntimeError(f"최대 재시도 초과 (연결 오류)") from e

        except requests.exceptions.RequestException as e:
            wait = GEMINI_RETRY_WAITS[attempt - 1]
            last_error = str(e)
            if remaining > 0:
                print(f"  -> [Gemini] 요청 오류({last_error}) -- {wait}초 대기 ({attempt}/{GEMINI_MAX_RETRIES}, 남은: {remaining}회)")
                time.sleep(wait)
            else:
                raise RuntimeError(f"최대 재시도 초과: {last_error}") from e

    raise RuntimeError(f"{GEMINI_MAX_RETRIES}회 시도 모두 실패: {last_error}")


# =====================================================================
# 이미지 생성 유틸리티
# =====================================================================

def _make_gradient_background(size, colors):
    w, h = size
    base = Image.new("RGB", size, colors[0])
    top  = Image.new("RGB", size, colors[-1])
    mask = Image.new("L", size)
    mask.putdata([int(((x / w + y / h) / 2) * 255) for y in range(h) for x in range(w)])
    blended = Image.composite(top, base, mask)
    mid = Image.new("RGB", size, colors[1])
    mid_mask = Image.new("L", size)
    mid_mask.putdata([int(80 * (1 - abs((x / w + y / h) / 2 - 0.5) * 2)) for y in range(h) for x in range(w)])
    return Image.composite(mid, blended, mid_mask)


def _fetch_pollinations(prompt, size, seed, timeout=20):
    url = (
        f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}"
        f"?width={size[0]}&height={size[1]}&seed={seed}&nologo=true"
    )
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
        return img.resize(size) if img.size != size else img
    except Exception as e:
        print(f"  -> [이미지] Pollinations 실패: {e}")
        return None


def _wrap_by_pixel_width(draw, text, font, max_width):
    words = text.split(" ")
    lines, current = [], ""

    def width_of(s):
        bbox = draw.textbbox((0, 0), s, font=font)
        return bbox[2] - bbox[0]

    for word in words:
        candidate = f"{current} {word}".strip()
        if width_of(candidate) <= max_width:
            current = candidate
        elif not current:
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


def generate_thumbnail(title, output_path, theme, category="라이프스타일"):
    img = _make_gradient_background(THUMB_SIZE, theme["gradient"]).convert("RGBA")
    seed = int(hashlib.md5(title.encode("utf-8")).hexdigest(), 16) % 100000
    prompt = ILLUSTRATION_PROMPTS.get(category, ILLUSTRATION_PROMPTS["라이프스타일"]) + ILLUSTRATION_SUFFIX
    illus = _fetch_pollinations(prompt, THUMB_SIZE, seed)
    if illus:
        img = Image.blend(img, illus, alpha=0.10)

    draw       = ImageDraw.Draw(img)
    accent_rgb = _hex_to_rgb(theme["accent"])

    label_font = _load_font(32)
    label_text = theme["label"]
    lb         = draw.textbbox((0, 0), label_text, font=label_font)
    pad_x, pad_y = 22, 10
    badge_w = (lb[2] - lb[0]) + pad_x * 2
    badge_h = (lb[3] - lb[1]) + pad_y * 2
    badge_x = (THUMB_SIZE[0] - badge_w) // 2
    badge_y = 75
    draw.rounded_rectangle([badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
                            radius=badge_h // 2, fill=accent_rgb + (255,))
    draw.text((badge_x + pad_x, badge_y + pad_y - lb[1]), label_text, font=label_font, fill=(255, 255, 255, 255))

    bar_h = 18
    draw.rectangle([(0, THUMB_SIZE[1] - bar_h), (THUMB_SIZE[0], THUMB_SIZE[1])], fill=accent_rgb + (255,))

    max_text_width  = 620
    max_text_height = int(THUMB_SIZE[1] * 0.65)
    font_size       = 64
    font = None
    lines = []
    total_h = 0
    while font_size >= 24:
        font  = _load_font(font_size)
        lines = _wrap_by_pixel_width(draw, title, font, max_text_width)[:4]
        heights = [draw.textbbox((0, 0), l, font=font)[3] - draw.textbbox((0, 0), l, font=font)[1] for l in lines]
        total_h = sum(heights) + (len(lines) - 1) * 16
        full_count = len(_wrap_by_pixel_width(draw, title, font, max_text_width))
        if total_h <= max_text_height and full_count <= 4:
            break
        font_size -= 4

    if len(_wrap_by_pixel_width(draw, title, font, max_text_width)) > 4:
        last = lines[-1]
        while draw.textbbox((0, 0), last + "...", font=font)[2] > max_text_width and len(last) > 1:
            last = last[:-1]
        lines[-1] = last.rstrip(".,!? ") + "..."

    heights = [draw.textbbox((0, 0), l, font=font)[3] - draw.textbbox((0, 0), l, font=font)[1] for l in lines]
    total_h = sum(heights) + (len(lines) - 1) * 16
    y = (THUMB_SIZE[1] - total_h) / 2 + 50

    for line, lh in zip(lines, heights):
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (THUMB_SIZE[0] - (bbox[2] - bbox[0])) / 2
        draw.text((x + 4, y + 4), line, font=font, fill=(0, 0, 0, 160))
        draw.text((x, y),         line, font=font, fill=(255, 255, 255, 255))
        y += lh + 16

    img.convert("RGB").save(output_path, format="WEBP", quality=82, method=6)


def generate_site_logo(output_path):
    img  = _make_gradient_background(LOGO_SIZE, BRAND_GRADIENT).convert("RGBA")
    draw = ImageDraw.Draw(img)
    w, h = LOGO_SIZE
    margin = 36
    draw.ellipse([margin, margin, w - margin, h - margin], outline=BRAND_ACCENT + (255,), width=10)
    initial  = (SITE_TITLE.strip()[:1] or "B")
    font     = _load_font(220)
    bbox     = draw.textbbox((0, 0), initial, font=font)
    tw, th   = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((w - tw) / 2 - bbox[0], (h - th) / 2 - bbox[1]), initial, font=font, fill=(255, 255, 255, 255))
    img.convert("RGB").save(output_path, format="WEBP", quality=90)


def generate_site_banner(output_path):
    img  = _make_gradient_background(BANNER_SIZE, BRAND_GRADIENT).convert("RGBA")
    draw = ImageDraw.Draw(img)
    w, h = BANNER_SIZE
    draw.rectangle([(0, 0), (w, 8)], fill=BRAND_ACCENT + (255,))
    title_font   = _load_font(88)
    tagline_font = _load_font(32)
    tb = draw.textbbox((0, 0), SITE_TITLE, font=title_font)
    tw = tb[2] - tb[0]
    ty = h / 2 - 60
    draw.text(((w - tw) / 2, ty), SITE_TITLE, font=title_font, fill=(255, 255, 255, 255))
    lb = draw.textbbox((0, 0), SITE_TAGLINE, font=tagline_font)
    lw = lb[2] - lb[0]
    draw.text(((w - lw) / 2, ty + 110), SITE_TAGLINE, font=tagline_font, fill=BRAND_ACCENT + (255,))
    img.convert("RGB").save(output_path, format="WEBP", quality=88)


def ensure_brand_assets():
    os.makedirs(DOCS_DIR, exist_ok=True)
    logo_path = os.path.join(DOCS_DIR, "logo.webp")
    generate_site_logo(logo_path)
    generate_site_banner(os.path.join(DOCS_DIR, "banner.webp"))
    favicon_path = os.path.join(DOCS_DIR, "favicon.png")
    with Image.open(logo_path) as im:
        im.convert("RGB").resize((64, 64)).save(favicon_path, format="PNG")


# =====================================================================
# 콘텐츠 보강 함수들
# =====================================================================

def build_decor_html(theme, seed):
    rng    = random.Random(seed)
    emojis = theme["decor"]
    items  = []
    for _ in range(rng.randint(9, 12)):
        emoji   = rng.choice(emojis)
        top     = rng.randint(0, 96)
        left    = rng.randint(0, 92)
        size    = rng.randint(26, 58)
        rotate  = rng.randint(-30, 30)
        opacity = round(rng.uniform(0.07, 0.16), 2)
        items.append(
            f'<span class="decor-item" style="top:{top}%;left:{left}%;font-size:{size}px;'
            f'opacity:{opacity};transform:rotate({rotate}deg);">{emoji}</span>'
        )
    return '<div class="decor-layer" aria-hidden="true">' + "".join(items) + "</div>"


def _search_console_meta():
    if not GOOGLE_SITE_VERIFICATION:
        return ""
    return f'\n<meta name="google-site-verification" content="{GOOGLE_SITE_VERIFICATION}">'


def _ga_snippet():
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


def _adsense_snippet():
    if not ADSENSE_CLIENT_ID:
        return ""
    return (
        f'\n<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js'
        f'?client={ADSENSE_CLIENT_ID}" crossorigin="anonymous"></script>'
    )


def _translate_widget():
    if not ENABLE_AUTO_TRANSLATE:
        return ""
    return """
<div style="position:fixed;top:10px;right:10px;z-index:999;">
  <button onclick="var e=document.getElementById('gt-box');e.style.display=(e.style.display==='none'||!e.style.display)?'block':'none';"
    style="width:38px;height:38px;border-radius:50%;border:none;background:#fff;box-shadow:0 2px 8px rgba(0,0,0,0.25);font-size:17px;cursor:pointer;line-height:1;">\U0001f310</button>
  <div id="gt-box" style="display:none;margin-top:6px;background:#fff;padding:6px 8px;border-radius:10px;box-shadow:0 2px 10px rgba(0,0,0,0.18);">
    <div id="google_translate_element"></div>
  </div>
</div>
<script>
function googleTranslateElementInit() {
  new google.translate.TranslateElement({pageLanguage: 'ko', autoDisplay: false}, 'google_translate_element');
}
</script>
<script src="//translate.google.com/translate_a/element.js?cb=googleTranslateElementInit"></script>"""


def _build_tts_widget(accent, content_selector=".content"):
    if not ENABLE_TTS:
        return ""
    return f"""
<div style="position:fixed;bottom:20px;right:20px;z-index:998;">
  <button id="tts-btn" type="button" onclick="window.__ttsToggle && window.__ttsToggle();"
    style="width:50px;height:50px;border-radius:50%;border:none;background:{accent};color:#fff;
    font-size:20px;box-shadow:0 3px 12px rgba(0,0,0,0.28);cursor:pointer;">\U0001f50a</button>
</div>
<script>
(function() {{
  var synth = window.speechSynthesis;
  if (!synth) return;
  var speaking = false;
  function pickVoice() {{
    var voices = synth.getVoices() || [];
    var ko = voices.filter(function(v) {{ return v.lang && v.lang.toLowerCase().indexOf('ko') === 0; }});
    var female = ko.filter(function(v) {{ return /female|\uc5ec\uc131|\uc720\ub098|\ubcf4\ub77c|\uc11c\uc5f0|\uc9c0\ubbfc/i.test(v.name); }});
    return female[0] || ko[0] || null;
  }}
  function updateBtn() {{
    var btn = document.getElementById('tts-btn');
    if (btn) btn.textContent = speaking ? '\u23f8\ufe0f' : '\U0001f50a';
  }}
  function speak() {{
    var content = document.querySelector('{content_selector}');
    if (!content) return;
    var text = (content.innerText || content.textContent || '').trim().slice(0, 3000);
    if (!text) return;
    var utter = new SpeechSynthesisUtterance(text);
    var voice = pickVoice();
    if (voice) utter.voice = voice;
    utter.lang = 'ko-KR'; utter.rate = 0.92; utter.pitch = 1.0;
    utter.onend = function() {{ speaking = false; updateBtn(); }};
    utter.onerror = function() {{ speaking = false; updateBtn(); }};
    synth.cancel(); synth.speak(utter);
    speaking = true; updateBtn();
  }}
  window.__ttsToggle = function() {{
    if (speaking) {{ synth.cancel(); speaking = false; updateBtn(); }} else {{ speak(); }}
  }};
  setTimeout(function() {{ try {{ speak(); }} catch (e) {{}} }}, 1000);
}})();
</script>"""


def _manual_ad_unit():
    if not (ADSENSE_CLIENT_ID and ADSENSE_SLOT_ID):
        return ""
    return (
        '<div style="margin:28px 0;text-align:center;">'
        f'<ins class="adsbygoogle" style="display:block" data-ad-client="{ADSENSE_CLIENT_ID}" '
        f'data-ad-slot="{ADSENSE_SLOT_ID}" data-ad-format="auto" data-full-width-responsive="true"></ins>'
        '<script>(adsbygoogle = window.adsbygoogle || []).push({});</script>'
        '</div>'
    )


def build_faq_section_html(article, accent="#4a90d9"):
    if not article.get("faq_items"):
        return ""
    cards = []
    for i, qa in enumerate(article["faq_items"], 1):
        question = qa.get("question", "")
        answer   = qa.get("answer", "")
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
        '<h2 style="margin-top:2em;">\uc790\uc8fc \ubb3b\ub294 \uc9c8\ubb38(FAQ) '
        '<span style="font-size:0.6em;color:#999;font-weight:400;">(\ud0ed\ud558\uba74 \ud3bc\uccd0\uc694)</span></h2>'
        + "".join(cards)
    )


def build_json_ld(article, canonical_url, thumb_url, date, platform="github"):
    schema_type  = article.get("schema_type", "Article")
    title        = article["title"]
    meta_desc    = article.get("meta_description", "")
    article_type = "BlogPosting" if platform == "blogger" else "Article"

    if schema_type == "FAQPage" and article.get("faq_items"):
        data = {
            "@context": "https://schema.org",
            "@type":    "FAQPage",
            "mainEntity": [
                {"@type": "Question", "name": qa.get("question", ""),
                 "acceptedAnswer": {"@type": "Answer", "text": qa.get("answer", "")}}
                for qa in article["faq_items"]
            ],
        }
    elif schema_type == "HowTo" and article.get("howto_steps"):
        data = {
            "@context": "https://schema.org",
            "@type":    "HowTo",
            "name":        title,
            "description": meta_desc,
            "step": [
                {"@type": "HowToStep", "name": s.get("name", ""), "text": s.get("text", "")}
                for s in article["howto_steps"]
            ],
        }
    else:
        schema_type = article_type
        data = {
            "@context":    "https://schema.org",
            "@type":       article_type,
            "headline":    title,
            "description": meta_desc,
            "image":       thumb_url,
            "datePublished": date,
            "author": {"@type": "Organization", "name": SITE_TITLE},
        }

    data.pop("@context", None)
    breadcrumb = {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": SITE_TITLE,
             "item": (SITE_URL + "/") if SITE_URL else "../index.html"},
            {"@type": "ListItem", "position": 2, "name": article.get("category", "\ub77c\uc774\ud504\uc2a4\ud0c0\uc77c"),
             "item": (SITE_URL + "/") if SITE_URL else "../index.html"},
            {"@type": "ListItem", "position": 3, "name": title, "item": canonical_url},
        ],
    }
    graph_nodes = [data, breadcrumb]

    products = article.get("product_list") or []
    if products:
        graph_nodes.append({
            "@type": "ItemList",
            "name":  f"{title} - \uc18c\uac1c\ub41c \uc0c1\ud488 \ubaa9\ub85d",
            "itemListElement": [
                {"@type": "ListItem", "position": i,
                 "item": {"@type": "Product", "name": p.get("name", ""), "description": p.get("description", "")}}
                for i, p in enumerate(products[:6], 1)
            ],
        })
        print(f"  -> [\uc2a4\ud0a4\ub9c8] ItemList \ucd94\uac00 (\uc0c1\ud488 {len(products[:6])}\uac1c)")

    graph_data = {"@context": "https://schema.org", "@graph": graph_nodes}
    print(f"  -> [\uc2a4\ud0a4\ub9c8] AI \uc120\ud0dd \ud0c0\uc785: {schema_type} (+ BreadcrumbList)")
    return json.dumps(graph_data, ensure_ascii=False, indent=2)


def build_blog_index_json_ld(posts):
    data = {
        "@context": "https://schema.org",
        "@type":    "Blog",
        "name":     SITE_TITLE,
        "url":      (SITE_URL + "/") if SITE_URL else ".",
        "blogPost": [
            {"@type": "BlogPosting", "headline": p["title"],
             "url":           (f"{SITE_URL}/{p['file']}" if SITE_URL else p["file"]),
             "datePublished": p["date"],
             "image":         (f"{SITE_URL}/{p['thumb']}" if SITE_URL else p["thumb"])}
            for p in posts[:10]
        ],
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


def enhance_tables(html_body, accent):
    counter = {"n": 0}

    def wrap_table(match):
        counter["n"] += 1
        uid        = f"tblzoom{counter['n']}_{random.randint(1000, 9999)}"
        table_html = match.group(0)
        styled     = re.sub(r"<table(?![^>]*style=)",
                            '<table style="width:100%;min-width:460px;border-collapse:collapse;"',
                            table_html, count=1)
        modal      = re.sub(r"<table(?![^>]*style=)",
                            '<table style="width:100%;min-width:420px;border-collapse:collapse;"',
                            table_html, count=1)
        return (
            f'<div style="overflow-x:auto;-webkit-overflow-scrolling:touch;margin:1.2em 0 0.4em;'
            f'border-radius:8px;border:1px solid #eee;">{styled}</div>'
            f'<div style="text-align:right;margin:0 0 1.2em;">'
            f'<button type="button" onclick="document.getElementById(\'{uid}\').style.display=\'flex\';" '
            f'style="border:none;background:none;color:{accent};font-size:0.85em;font-weight:700;'
            f'cursor:pointer;padding:4px 2px;">\U0001f50d \ud45c \ud06c\uac8c \ubcf4\uae30</button></div>'
            f'<div id="{uid}" '
            f'style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.82);'
            f'z-index:1000;align-items:center;justify-content:center;padding:16px;" '
            f'onclick="if(event.target===this){{this.style.display=\'none\';}}">'
            f'<div style="background:#fff;border-radius:12px;padding:18px;max-width:95vw;max-height:88vh;overflow:auto;">'
            f'<button type="button" onclick="document.getElementById(\'{uid}\').style.display=\'none\';" '
            f'style="display:block;margin:0 0 10px auto;width:32px;height:32px;border-radius:50%;'
            f'border:none;background:#f0f0f0;font-size:1em;cursor:pointer;">\u2715</button>'
            f'{modal}</div></div>'
        )

    return re.sub(r"<table.*?</table>", wrap_table, html_body, flags=re.DOTALL)


def insert_content_image(article, slug):
    category = article.get("category", "\ub77c\uc774\ud504\uc2a4\ud0c0\uc77c")
    seed     = int(hashlib.md5((article["title"] + "-inline").encode("utf-8")).hexdigest(), 16) % 100000
    base_prompt = ILLUSTRATION_PROMPTS.get(category, ILLUSTRATION_PROMPTS["\ub77c\uc774\ud504\uc2a4\ud0c0\uc77c"])
    prompt      = base_prompt.replace("flat vector illustration of", "photo illustration of") + ", high quality, natural lighting"
    photo = _fetch_pollinations(prompt, (1000, 560), seed)
    if photo is None:
        return article

    filename = f"{slug}-inline.webp"
    path     = os.path.join(DOCS_DIR, "thumbs", filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    photo.convert("RGB").save(path, format="WEBP", quality=82, method=6)

    img_html = (
        f'<img src="../thumbs/{filename}" alt="{article["title"]} \uad00\ub828 \uc774\ubbf8\uc9c0" loading="lazy" '
        'style="width:100%;border-radius:10px;margin:20px 0;">'
    )
    idx = article["html_body"].find("</h2>")
    if idx != -1:
        insert_at = idx + len("</h2>")
        article["html_body"] = article["html_body"][:insert_at] + img_html + article["html_body"][insert_at:]
    else:
        article["html_body"] = img_html + article["html_body"]
    return article


def build_product_list_html(article, slug, accent):
    products = article.get("product_list") or []
    if not products:
        return ""
    os.makedirs(os.path.join(DOCS_DIR, "thumbs"), exist_ok=True)
    cards = []
    for i, item in enumerate(products[:6], 1):
        name = item.get("name", "")
        desc = item.get("description", "")
        seed = int(hashlib.md5(f"{slug}-product-{i}".encode("utf-8")).hexdigest(), 16) % 100000
        prompt = (
            f"minimalist pencil sketch icon of {name}, single centered object, "
            "clean line art, simple outline, white background, no text, no watermark"
        )
        icon = _fetch_pollinations(prompt, (160, 160), seed, timeout=15)
        if icon is not None:
            icon_filename = f"{slug}-product{i}.webp"
            icon.convert("RGB").save(os.path.join(DOCS_DIR, "thumbs", icon_filename), format="WEBP", quality=80)
            icon_html = f'<img src="../thumbs/{icon_filename}" alt="{name}" loading="lazy" style="width:56px;height:56px;border-radius:10px;object-fit:cover;flex-shrink:0;">'
        else:
            icon_html = f'<div style="width:56px;height:56px;border-radius:10px;background:{accent}22;flex-shrink:0;"></div>'
        cards.append(
            '<div style="display:flex;gap:14px;align-items:center;margin:10px 0;padding:12px 14px;'
            f'background:#f7f8fa;border-radius:10px;">{icon_html}'
            f'<div><p style="margin:0 0 3px;font-weight:700;color:#111;">{name}</p>'
            f'<p style="margin:0;color:#555;font-size:0.92em;line-height:1.5;">{desc}</p></div></div>'
        )
    return '<h2 style="margin-top:2em;">\ud55c\ub208\uc5d0 \ubcf4\ub294 \uc0c1\ud488 \ubaa9\ub85d</h2>' + "".join(cards)


def _relevance_score(article, candidate):
    score = 3.0 if candidate.get("category") == article.get("category") else 0.0
    current_words   = set(re.findall(r"[\w\uac00-\ud7a3]+", (article.get("title", "") + " " + article.get("keyword", ""))))
    candidate_words = set(re.findall(r"[\w\uac00-\ud7a3]+", candidate.get("title", "")))
    score += len(current_words & candidate_words) * 1.5
    return score


def add_internal_link(article):
    if not os.path.exists(POSTS_JSON):
        return article
    with open(POSTS_JSON, "r", encoding="utf-8") as f:
        posts = json.load(f)
    if not posts:
        return article
    scored   = sorted([(p, _relevance_score(article, p)) for p in posts], key=lambda x: x[1], reverse=True)
    top_pool = [p for p, s in scored[:5] if s > 0] or [p for p, s in scored[:5]]
    if not top_pool:
        return article
    weights = [max(s, 0.5) for p, s in scored[:len(top_pool)]]
    pick    = random.choices(top_pool, weights=weights, k=1)[0]
    article["html_body"] += (
        f'<p style="margin-top:2em;padding-top:1em;border-top:1px dashed #ddd;">'
        f'\U0001f517 \uc774 \uae00\ub3c4 \ud568\uaed8 \ubcf4\uba74 \uc88b\uc544\uc694: <a href="../{pick["file"]}">{pick["title"]}</a></p>'
    )
    return article


def insert_manual_ads(article):
    ad_html = _manual_ad_unit()
    if not ad_html:
        return article
    idx = article["html_body"].find("<h2")
    if idx != -1:
        article["html_body"] = article["html_body"][:idx] + ad_html + article["html_body"][idx:]
    else:
        article["html_body"] += ad_html
    return article


def add_coupang_markup(article):
    product_keyword = (article.get("product_keyword") or "").strip()
    if not product_keyword:
        print("  -> \ub9c8\ud06c\uc5c5: \uc0c1\ud488 \ubbf8\uad00\ub828 \uc8fc\uc81c, \ucd94\ucc9c \uc139\uc158 \uc0dd\ub7b5")
        return article

    search_url = f"https://www.coupang.com/np/search?q={urllib.parse.quote(product_keyword)}"
    if COUPANG_PARTNER_TAG:
        search_url += f"&lptag={COUPANG_PARTNER_TAG}"

    link = _coupang_deeplink(search_url) or search_url
    link_type = "\ucfe0\ud305\ud30c\ud2b8\ub108\uc2a4 \ub525\ub9c1\ud06c" if link != search_url else "\uc77c\ubc18 \uac80\uc0c9 \ub9c1\ud06c"
    print(f"  -> \ub9c8\ud06c\uc5c5 \ubc29\uc2dd: {link_type} (\uac80\uc0c9\uc5b4: {product_keyword})")

    article["html_body"] += (
        f'<h2>\uad00\ub828 \ucd94\ucc9c \uc0c1\ud488</h2>'
        f'<p><a href="{link}" target="_blank" rel="nofollow sponsored">{product_keyword} \uad00\ub828 \uc778\uae30 \uc0c1\ud488 \ubcf4\ub7ec\uac00\uae30</a></p>'
        '<p style="font-size:0.85em;color:#888;">\uc774 \ud3ec\uc2a4\ud305\uc740 \ucfe0\ud321 \ud30c\ud2b8\ub108\uc2a4 \ud65c\ub3d9\uc758 \uc77c\ud658\uc73c\ub85c, '
        '\uc774\uc5d0 \ub530\ub978 \uc77c\uc815\uc561\uc758 \uc218\uc218\ub8cc\ub97c \uc81c\uacf5\ubc1b\uc2b5\ub2c8\ub2e4.</p>'
    )
    return article


def _coupang_deeplink(search_url):
    if not (COUPANG_ACCESS_KEY and COUPANG_SECRET_KEY):
        return None
    domain = "https://api-gateway.coupang.com"
    path   = "/v2/providers/affiliate_open_api/apis/openapi/v1/deeplink"
    try:
        query           = urllib.parse.urlencode({"coupangUrls": search_url})
        path_with_query = f"{path}?{query}"
        datetime_str    = time.strftime("%y%m%dT%H%M%SZ", time.gmtime())
        message         = datetime_str + "GET" + path_with_query
        signature       = hmac.new(COUPANG_SECRET_KEY.encode(), message.encode(), hashlib.sha256).hexdigest()
        auth_header     = (
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
        print(f"  -> [\ucfe0\ud321 \ub525\ub9c1\ud06c] \ubc1c\uae09 \uc2e4\ud328: {e}")
        return None


def add_ymyl_disclaimer(article):
    theme = get_theme(article.get("category", "\ub77c\uc774\ud504\uc2a4\ud0c0\uc77c"))
    if not theme.get("ymyl"):
        return article
    article["html_body"] += (
        '<div style="background:#fff8e1;border:1px solid #ffe082;border-radius:10px;'
        'padding:14px 18px;margin:24px 0;font-size:0.92em;color:#5d4037;">'
        '\u26a0\ufe0f <b>\uc548\ub0b4:</b> \uc774 \uae00\uc740 \uc77c\ubc18\uc801\uc778 \uc815\ubcf4 \uc81c\uacf5 \ubaa9\uc801\uc73c\ub85c \uc791\uc131\ub418\uc5c8\uc73c\uba70, \ud2b9\uc815 \uc0c1\ud488\xb7\uae30\uad00\uc744 \ubcf4\uc99d\ud558\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4. '
        '\uae08\ub9ac, \uc790\uaca9 \uc694\uac74, \uc9c0\uc6d0\uae08\uc561, \uc2e0\uccad \uae30\uac04 \ub4f1\uc740 \uc218\uc2dc\ub85c \ubc14\ub0c0 \uc218 \uc788\uc73c\ub2c8 '
        '\ubc18\ub4dc\uc2dc \ud574\ub2f9 \uae08\uc735\uae30\uad00 \ub610\ub294 \uc815\ubd8024\xb7\uad00\ud560 \uc9c0\uc790\uccb4 \ub4f1 \uacf5\uc2dd \ucc44\ub110\uc5d0\uc11c \ucd5c\uc2e0 \uc815\ubcf4\ub97c \ud655\uc778\ud558\uc138\uc694.'
        '</div>'
    )
    return article


# =====================================================================
# 포스트 저장 / 인덱스 갱신
# =====================================================================

def _build_post_nav_html():
    prev_post = None
    if os.path.exists(POSTS_JSON):
        with open(POSTS_JSON, "r", encoding="utf-8") as f:
            posts = json.load(f)
        if posts:
            prev_post = posts[0]
    prev_html = (
        f'<a href="../{prev_post["file"]}"><img src="../{prev_post["thumb"]}" alt="\uc774\uc804 \uac8c\uc2dc\ubb3c">'
        f'<span>\u2190 \uc774\uc804 \uac8c\uc2dc\ubb3c: {prev_post["title"]}</span></a>'
        if prev_post else
        '<a href="../index.html"><span class="nav-icon">\U0001f3e0</span><span>\ubaa9\ub85d\uc73c\ub85c</span></a>'
    )
    return (
        f'<div class="post-nav">{prev_html}'
        '<a href="../index.html"><span class="nav-icon">\U0001f4f0</span><span>\ucd5c\uc2e0 \uac8c\uc2dc\ubb3c \ubcf4\uae30</span></a></div>'
    )


def _build_related_html(exclude_slug):
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
    return f'<div class="related"><h3>\U0001f4cc \ud568\uaed8 \ubcf4\uba74 \uc88b\uc740 \uae00</h3><div class="related-grid">{cards}</div></div>'


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
  html {{ -webkit-text-size-adjust: 100%; }}
  body {{ position: relative; width: 100%; max-width: 720px; margin: 0 auto; padding: 0 clamp(16px, 4vw, 20px) 60px; font-family: 'Noto Sans KR', -apple-system, sans-serif; line-height: 1.75; color: #1a1a1a; background: #fafafa; overflow-x: hidden; }}
  img {{ max-width: 100%; height: auto; }}
  .decor-layer {{ position: absolute; inset: 0; overflow: hidden; pointer-events: none; z-index: 0; }}
  .decor-item {{ position: absolute; user-select: none; }}
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
  details summary::after {{ content: '\u25bc'; font-size: 0.75em; color: {accent}; flex-shrink: 0; }}
  details[open] summary::after {{ content: '\u25b2'; }}
  @media (max-width: 480px) {{ .related-grid {{ grid-template-columns: 1fr 1fr; }} .post-nav a {{ font-size: 0.78em; flex: 1 1 100%; }} }}
  @media (min-width: 900px) {{ body {{ max-width: 760px; }} }}
  body {{ top: 0 !important; }}
  .goog-te-banner-frame {{ display: none !important; }}
</style>
</head>
<body>
{translate_widget}
{tts_widget}
{decor_html}
<div class="content">
<a class="back" href="../index.html">\u2190 \ubaa9\ub85d\uc73c\ub85c</a>
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

INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{site_title}</title>
<meta name="description" content="{site_title} - \uc790\ub3d9\uc73c\ub85c \uc5c5\ub370\uc774\ud2b8\ub418\ub294 \ube14\ub85c\uadf8">
<link rel="canonical" href="{site_url}/">
<link rel="icon" type="image/png" href="favicon.png">{search_console_meta}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="{fonts_url}" rel="stylesheet">
<script type="application/ld+json">
{blog_json_ld}
</script>{ga_snippet}{adsense_snippet}
<style>
  * {{ box-sizing: border-box; }} html {{ -webkit-text-size-adjust: 100%; }}
  body {{ max-width: 1000px; margin: 0 auto; padding: 0 0 60px; font-family: 'Noto Sans KR', -apple-system, sans-serif; background:#f5f5f7; color:#1a1a1a; }}
  img {{ max-width: 100%; height: auto; }}
  .masthead {{ margin-bottom: 26px; }} .masthead img {{ width: 100%; aspect-ratio: 1600/420; object-fit: cover; display:block; }}
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
  @media (max-width: 480px) {{ .masthead img {{ aspect-ratio: 1600/620; }} .mid-grid {{ grid-template-columns: 1fr; gap: 14px; }} .bottom-grid {{ grid-template-columns: repeat(2, 1fr); }} }}
  @media (min-width: 1000px) {{ .bottom-grid {{ grid-template-columns: repeat(5, 1fr); }} }}
  body {{ top: 0 !important; }} .goog-te-banner-frame {{ display: none !important; }}
</style>
</head>
<body>
{translate_widget}
<div class="masthead"><img src="banner.webp" alt="{site_title}" loading="eager" fetchpriority="high"></div>
<div class="masthead-inner">
  <div class="brand-row">
    <img class="logo" src="logo.webp" alt="{site_title} \ub85c\uace0">
    <h1 class="site-title">{site_title}</h1>
    <a class="dash-link" href="dashboard.html">\U0001f4ca \uc131\uacfc\uad00\ub9ac</a>
  </div>
  <p class="intro">{site_tagline}</p>
  <div class="pill-row">{category_pills}</div>
</div>
<div class="content-wrap">{hero_html}{mid_html}{bottom_html}</div>
{footer_html}
</body>
</html>
"""

DASHBOARD_TEMPLATE = """<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>\uc131\uacfc \uad00\ub9ac - {site_title}</title>
<style>body{{max-width:760px;margin:40px auto;padding:0 20px;font-family:-apple-system,sans-serif;color:#222;}}h1{{font-size:1.5em;}}h2{{font-size:1.1em;margin-top:2em;}}table{{width:100%;border-collapse:collapse;font-size:0.9em;}}th,td{{text-align:left;padding:8px 4px;border-bottom:1px solid #eee;}}a{{color:#4a90d9;}}.card{{background:#f7f7f9;border-radius:8px;padding:16px;margin:10px 0;}}a.back{{display:inline-block;margin-bottom:20px;color:#4a90d9;text-decoration:none;}}</style>
</head><body>
<a class="back" href="index.html">\u2190 \ube14\ub85c\uadf8\ub85c</a>
<h1>\U0001f4ca \uc131\uacfc \uad00\ub9ac \ub300\uc2dc\ubcf4\ub4dc</h1>
<div class="card"><b>GA4 \ud2b8\ub798\ud53d</b><br><a href="https://analytics.google.com" target="_blank">analytics.google.com</a></div>
<div class="card"><b>\ucfe0\ud321 \uc218\uc218\ub8cc</b><br><a href="https://partners.coupang.com" target="_blank">partners.coupang.com</a></div>
<div class="card"><b>\uc560\ub4dc\uc13c\uc2a4 \uc218\uc775</b><br><a href="https://www.google.com/adsense" target="_blank">adsense.google.com</a></div>
<div class="card"><b>Search Console</b><br><a href="https://search.google.com/search-console" target="_blank">search.google.com/search-console</a></div>
<h2>\ubc1c\ud589\ub41c \uae00 ({post_count}\uac1c)</h2>
<table><tr><th>\ub0a0\uc9dc</th><th>\uc81c\ubaa9</th><th>\ubc14\ub85c\uac00\uae30</th></tr>{rows}</table>
</body></html>
"""

STATIC_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{page_title} - {site_title}</title>
<link rel="icon" type="image/png" href="favicon.png">{search_console_meta}{ga_snippet}{adsense_snippet}
<style>body{{max-width:680px;margin:0 auto;padding:40px 20px 60px;font-family:'Noto Sans KR',-apple-system,sans-serif;line-height:1.8;color:#222;}}h1{{font-size:1.6em;}}h2{{font-size:1.15em;margin-top:1.6em;}}a.back{{color:#4a90d9;text-decoration:none;display:inline-block;margin-bottom:20px;}}</style>
</head><body>
<a class="back" href="index.html">\u2190 \ud648\uc73c\ub85c</a>
<h1>{page_title}</h1>{page_body}
</body></html>
"""


def build_footer_html():
    return (
        '<div class="site-footer">'
        '<a href="about.html">\ube14\ub85c\uadf8 \uc18c\uac1c</a>\xb7'
        '<a href="privacy.html">\uac1c\uc778\uc815\ubcf4\ucc98\ub9ac\ubc29\uce68</a>\xb7'
        '<a href="contact.html">\ubb38\uc758\ud558\uae30</a>'
        f'<div style="margin-top:8px;">\xa9 {datetime.now().year} {SITE_TITLE}</div>'
        '</div>'
    )


def generate_static_pages():
    os.makedirs(DOCS_DIR, exist_ok=True)
    common = dict(site_title=SITE_TITLE, search_console_meta=_search_console_meta(),
                  ga_snippet=_ga_snippet(), adsense_snippet=_adsense_snippet())
    pages = {
        "about.html": ("\ube14\ub85c\uadf8 \uc18c\uac1c",
                       f"<p>{SITE_TITLE}\uc5d0 \uc624\uc2e0 \uac83\uc744 \ud658\uc601\ud569\ub2c8\ub2e4.</p><p>{SITE_TAGLINE}</p>"
                       "<p>\uc774 \ube14\ub85c\uadf8\ub294 AI \ub3c4\uad6c\ub97c \ud65c\uc6a9\ud569\ub2c8\ub2e4. \uac8c\uc2dc\ub41c \uc815\ubcf4\ub294 \ucc38\uace0\uc6a9\uc774\uba70, \uc911\uc694\ud55c \uacb0\uc815\uc744 \ub0b4\ub9ac\uc2e4 \ub54c\ub294 \ubc18\ub4dc\uc2dc \uacf5\uc2dd \ucd9c\uccb4\ub97c \ud568\uaed8 \ud655\uc778\ud574\uc8fc\uc138\uc694.</p>"),
        "privacy.html": ("\uac1c\uc778\uc815\ubcf4\ucc98\ub9ac\ubc29\uce68",
                         "<p>\ubcf8 \ube14\ub85c\uadf8\ub294 GA4 \ubc0f \uc560\ub4dc\uc13c\uc2a4\ub97c \ud1b5\ud574 \ubc29\ubb38\uc790 \ud1b5\uacc4\uc640 \uad11\uace0\ub97c \uc81c\uacf5\ud560 \uc218 \uc788\uc2b5\ub2c8\ub2e4.</p>"
                         '<h2>\ucfe0\ud0a4 \ubc0f \uad11\uace0</h2><p>\uad6c\uae00\uc744 \ud3ec\ud568\ud55c \uc81c3\uc790 \uad11\uace0 \uacf5\uae09\uc5c5\uccb4\ub294 \ucfe0\ud0a4\ub97c \uc0ac\uc6a9\ud558\uc5ec \ub9de\ucda4 \uad11\uace0\ub97c \uac8c\uc7ac\ud569\ub2c8\ub2e4. <a href="https://adssettings.google.com" target="_blank">\uad6c\uae00 \uad11\uace0 \uc124\uc815</a>\uc5d0\uc11c \ube44\ud65c\uc131\ud654 \uac00\ub2a5\ud569\ub2c8\ub2e4.</p>'),
        "contact.html": ("\ubb38\uc758\ud558\uae30",
                         "<p>\ucf58\ud150\uce20 \ub9c8\ucf00\ud305 \uad00\ub828 \ubb38\uc758, \ud611\uc5c5 \uc81c\uc548, \uc624\ub958 \uc2e0\uace0 \ub4f1\uc740 \uc544\ub798 \uc774\uba54\uc77c\ub85c \uc5f0\ub77d \uc8fc\uc138\uc694.</p>"
                         "<p><b>\uc774\uba54\uc77c:</b> \uc774 \ud398\uc774\uc9c0\uc758 \ubb38\uad6c\ub97c \uc9c1\uc811 \uc5f4\uc5b4 \ubcf8\uc778\uc758 \uc5f0\ub77d\uccb4\ub85c \uc218\uc815\ud574\uc8fc\uc138\uc694.</p>"),
    }
    for filename, (page_title, page_body) in pages.items():
        path = os.path.join(DOCS_DIR, filename)
        if os.path.exists(path):
            continue
        with open(path, "w", encoding="utf-8") as f:
            f.write(STATIC_PAGE_TEMPLATE.format(page_title=page_title, page_body=page_body, **common))
        print(f"  -> [Static] {filename} \uc0dd\uc131\ub428")


def save_post(article):
    os.makedirs(POSTS_DIR, exist_ok=True)
    os.makedirs(os.path.join(DOCS_DIR, "thumbs"), exist_ok=True)

    category = article.get("category", "\ub77c\uc774\ud504\uc2a4\ud0c0\uc77c")
    theme    = get_theme(category)
    slug     = slugify(article["keyword"])
    today    = datetime.now().strftime("%Y-%m-%d")

    thumb_filename = f"{slug}-{today}.webp"
    post_filename  = f"{slug}-{today}.html"

    generate_thumbnail(article["title"], os.path.join(DOCS_DIR, "thumbs", thumb_filename), theme, category)

    cleaned_body = article["html_body"]
    cleaned_body = re.sub(r"<h[23]>\uc790\uc8fc\s*\ubb3b\ub294\s*\uc9c8\ubb38.*?</table>", "", cleaned_body, flags=re.DOTALL | re.IGNORECASE)
    article["html_body"] = cleaned_body
    article["html_body"] = enhance_tables(article["html_body"], theme["accent"])
    article = insert_content_image(article, slug)
    article["html_body"] += build_faq_section_html(article, theme["accent"])
    article["html_body"] += build_product_list_html(article, slug, theme["accent"])

    post_url  = f"{SITE_URL}/posts/{post_filename}" if SITE_URL else f"posts/{post_filename}"
    thumb_url = f"{SITE_URL}/thumbs/{thumb_filename}" if SITE_URL else f"../thumbs/{thumb_filename}"

    json_ld      = build_json_ld(article, post_url, thumb_url, today)
    related_html = _build_related_html(exclude_slug=f"posts/{post_filename}")
    post_nav     = _build_post_nav_html()
    decor_html   = build_decor_html(theme, seed=slug)

    html = POST_TEMPLATE.format(
        title=article["title"], meta_description=article.get("meta_description", ""),
        date=today, html_body=article["html_body"],
        thumb_filename=thumb_filename, canonical_url=post_url, thumb_url=thumb_url,
        json_ld=json_ld, ga_snippet=_ga_snippet(), adsense_snippet=_adsense_snippet(),
        font=theme["font"], font_family=_font_family_name(theme["font"]),
        accent=theme["accent"], badge=theme["badge"],
        related_html=related_html, post_nav=post_nav, decor_html=decor_html,
        bottom_ad=_manual_ad_unit(), search_console_meta=_search_console_meta(),
        translate_widget=_translate_widget(), tts_widget=_build_tts_widget(theme["accent"]),
    )
    with open(os.path.join(POSTS_DIR, post_filename), "w", encoding="utf-8") as f:
        f.write(html)

    post_meta      = {"title": article["title"], "file": f"posts/{post_filename}",
                      "thumb": f"thumbs/{thumb_filename}", "date": today,
                      "category": category, "accent": theme["accent"], "badge": theme["badge"]}
    local_thumb    = os.path.join(DOCS_DIR, "thumbs", thumb_filename)
    return post_meta, json_ld, thumb_url, local_thumb, post_url


def update_index(new_post):
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
            '<div class="tier-label">\U0001f525 \ucd5c\uc2e0 \uc774\uc57c\uae30</div>'
            f'<a class="hero" href="{p["file"]}"><img src="{p["thumb"]}" alt="{p["title"]}" loading="eager" fetchpriority="high">'
            f'<div class="hero-body"><span class="hero-badge" style="background:{p.get("accent","#4a90d9")}">{p.get("badge","")}</span>'
            f'<div class="hero-title">{p["title"]}</div><div class="date">{p["date"]}</div></div></a>'
        )
    mid_html = ""
    if mid_posts:
        cards = "\n".join(
            f'<a class="mid-card" href="{p["file"]}"><img src="{p["thumb"]}" alt="{p["title"]}" loading="lazy">'
            f'<div class="mid-body"><span class="badge-sm" style="background:{p.get("accent","#4a90d9")}">{p.get("badge","")}</span>'
            f'<div class="mid-title">{p["title"]}</div><div class="date">{p["date"]}</div></div></a>'
            for p in mid_posts
        )
        mid_html = f'<div class="tier-label">\U0001f4d6 \ub2e4\uc74c \uc774\uc57c\uae30</div><div class="mid-grid">{cards}</div>'
    bottom_html = ""
    if bottom_posts:
        cards = "\n".join(
            f'<a class="bottom-card" href="{p["file"]}"><img src="{p["thumb"]}" alt="{p["title"]}" loading="lazy">'
            f'<div class="bottom-body"><span class="badge-sm" style="background:{p.get("accent","#4a90d9")}">{p.get("badge","")}</span>'
            f'<div class="bottom-title">{p["title"]}</div></div></a>'
            for p in bottom_posts
        )
        bottom_html = f'<div class="tier-label">\U0001f5c2\ufe0f \uc9c0\ub09c \uae00 \ubaa8\uc544\ubcf4\uae30</div><div class="bottom-grid">{cards}</div>'

    category_pills = "".join(
        f'<span class="pill" style="background:{t["accent"]}">{t["badge"]}</span>'
        for t in CATEGORY_THEMES.values()
    )
    with open(os.path.join(DOCS_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(INDEX_TEMPLATE.format(
            site_title=SITE_TITLE, site_tagline=SITE_TAGLINE,
            site_url=SITE_URL or ".", ga_snippet=_ga_snippet(), adsense_snippet=_adsense_snippet(),
            fonts_url=_google_fonts_url(), hero_html=hero_html, mid_html=mid_html, bottom_html=bottom_html,
            blog_json_ld=build_blog_index_json_ld(posts), category_pills=category_pills,
            search_console_meta=_search_console_meta(), footer_html=build_footer_html(),
            translate_widget=_translate_widget(),
        ))
    return posts


def update_dashboard(posts):
    rows = "\n".join(
        f'<tr><td>{p["date"]}</td><td>{p["title"]}</td><td><a href="{p["file"]}">\ubcf4\uae30</a></td></tr>'
        for p in posts
    )
    with open(os.path.join(DOCS_DIR, "dashboard.html"), "w", encoding="utf-8") as f:
        f.write(DASHBOARD_TEMPLATE.format(site_title=SITE_TITLE, post_count=len(posts), rows=rows))


def update_seo_files(posts):
    if not SITE_URL:
        print("  -> [SEO] SITE_URL \ubbf8\uc124\uc815, sitemap/robots.txt \uc0dd\uc131 \uac74\ub108\ub127")
        return
    url_entries = "\n".join(f"<url><loc>{SITE_URL}/{p['file']}</loc></url>" for p in posts)
    with open(os.path.join(DOCS_DIR, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write(f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n<url><loc>{SITE_URL}/</loc></url>\n{url_entries}\n</urlset>\n')
    with open(os.path.join(DOCS_DIR, "robots.txt"), "w", encoding="utf-8") as f:
        f.write(f"User-agent: *\nAllow: /\n\nSitemap: {SITE_URL}/sitemap.xml\n")


# =====================================================================
# 블로거 발행
# =====================================================================

def _blogger_configured():
    return bool(BLOGGER_BLOG_ID and GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and GOOGLE_REFRESH_TOKEN)


def _get_blogger_access_token():
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={"client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET,
              "refresh_token": GOOGLE_REFRESH_TOKEN, "grant_type": "refresh_token"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _make_blogger_safe_html(html_body):
    if SITE_URL:
        html_body = html_body.replace('href="../posts/', f'href="{SITE_URL}/posts/')
        html_body = html_body.replace('href="../thumbs/', f'href="{SITE_URL}/thumbs/')
        html_body = html_body.replace('src="../thumbs/', f'src="{SITE_URL}/thumbs/')
    else:
        html_body = re.sub(r'<a href="\.\./(posts|thumbs)/[^"]*"[^>]*>(.*?)</a>', r"\2", html_body)
        html_body = re.sub(r'<img src="\.\./thumbs/[^"]*"[^>]*>', "", html_body)
    return html_body


def publish_to_blogger(article, canonical_url, thumb_url, local_thumb_path):
    if not _blogger_configured():
        print("  -> [\ube14\ub85c\uac70] Secrets \ubbf8\uc124\uc815, \uac74\ub108\ub07c")
        return
    try:
        access_token = _get_blogger_access_token()
        theme        = get_theme(article.get("category", "\ub77c\uc774\ud504\uc2a4\ud0c0\uc77c"))
        today        = datetime.now().strftime("%Y-%m-%d")
        blogger_json_ld = build_json_ld(article, canonical_url, thumb_url, today, platform="blogger")

        # SITE_URL 있으면 외부 URL 사용 (base64 크기 문제 방지), 없으면 base64 임베드
        if SITE_URL:
            img_src = thumb_url
        else:
            try:
                with open(local_thumb_path, "rb") as f:
                    img_b64 = base64.b64encode(f.read()).decode("ascii")
                img_src = f"data:image/webp;base64,{img_b64}"
            except Exception as e:
                print(f"  -> [\ube14\ub85c\uac70] base64 \uc778\ucf54\ub529 \uc2e4\ud328, \uc678\ubd80 \ub9c1\ud06c \ub300\uccb4: {e}")
                img_src = thumb_url

        content_html = (
            f'{_translate_widget()}'
            f'<div id="blogger-tts-content">'
            f'<img src="{img_src}" style="max-width:100%;border-radius:8px;" alt="{article["title"]}">'
            f'<span style="display:inline-block;background:{theme["accent"]};color:#fff;font-size:0.85em;'
            f'font-weight:bold;padding:4px 12px;border-radius:999px;margin:14px 0 4px;">{theme["badge"]}</span>'
            f'{_make_blogger_safe_html(article["html_body"])}'
            f'</div>'
            f'{_build_tts_widget(theme["accent"], content_selector="#blogger-tts-content")}'
            f'<script type="application/ld+json">{blogger_json_ld}</script>'
        )
        url     = f"https://www.googleapis.com/blogger/v3/blogs/{BLOGGER_BLOG_ID}/posts/"
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        resp    = requests.post(url, headers=headers, json={"title": article["title"], "content": content_html}, timeout=30)
        if not resp.ok:
            print(f"  -> [\ube14\ub85c\uac70] API \uc624\ub958 {resp.status_code}: {resp.text[:300]}")
            resp.raise_for_status()
        print(f"  -> [\ube14\ub85c\uac70] \ubc1c\ud589 \uc644\ub8cc: {resp.json().get('url', '(URL \ud655\uc778 \ubd88\uac00)')}")
    except Exception as e:
        print(f"  -> [\ube14\ub85c\uac70] \ubc1c\ud589 \uc2e4\ud328 (GitHub Pages\ub294 \uc815\uc0c1): {e}")


def ensure_nojekyll():
    os.makedirs(DOCS_DIR, exist_ok=True)
    p = os.path.join(DOCS_DIR, ".nojekyll")
    if not os.path.exists(p):
        open(p, "w").close()
        print("  -> .nojekyll \uc0dd\uc131")


# =====================================================================
# 메인
# =====================================================================

def run():
    title = get_title_from_args_or_queue()
    print(f"[\ucc98\ub9ac \uc2dc\uc791] \uc81c\ubaa9: {title}")

    ensure_nojekyll()
    ensure_brand_assets()
    generate_static_pages()

    article = generate_article(title)
    print(f"  -> \uae00 \uc0dd\uc131 \uc644\ub8cc: {article['title']}")

    article = add_internal_link(article)
    article = insert_manual_ads(article)
    article = add_coupang_markup(article)
    article = add_ymyl_disclaimer(article)
    post_meta, json_ld, thumb_url, local_thumb, post_url = save_post(article)
    posts = update_index(post_meta)
    update_dashboard(posts)
    update_seo_files(posts)
    publish_to_blogger(article, post_url, thumb_url, local_thumb)

    print(f"  -> \uc800\uc7a5 \uc644\ub8cc: docs/{post_meta['file']}")
    print(f"  -> \ub300\uc2dc\ubcf4\ub4dc/\uc0ac\uc774\ud2b8\ub9f5 \uac31\uc2e0 \uc644\ub8cc")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        print(f"[\uc624\ub958] {e}")
        sys.exit(1)

