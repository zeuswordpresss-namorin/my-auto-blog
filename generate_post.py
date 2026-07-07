# -*- coding: utf-8 -*-
"""
GitHub Actions 위에서 실행되는 자동 블로그 파이프라인 스크립트.
로컬 PC나 스마트폰에서 직접 실행하는 스크립트가 아니라,
.github/workflows/auto_blog.yml 이 GitHub 서버에서 대신 실행해줍니다.
(그래서 안드로이드폰에서도 "실행 버튼"만 누르면 관리가 가능합니다)

동작:
  1. 제목을 실행 인자로 받거나 (수동 실행 시), 없으면 keywords_queue.json에서
     다음 키워드를 하나 꺼내 씁니다 (예약 자동 실행 시).
  2. Gemini 무료 API로 글 생성
  3. Pillow로 Gemini스타일 그라데이션 썸네일 생성
  4. 쿠팡 마크업(제휴) 링크 삽입
  5. docs/posts/ 에 HTML 파일로 저장, docs/index.html 목록 갱신
     (실제 git commit/push는 워크플로 파일이 담당합니다)
"""

import io
import json
import os
import re
import sys
import textwrap
from datetime import datetime

import requests
from PIL import Image, ImageDraw, ImageFont

# =====================================================================
# 환경변수로 받는 설정값 (GitHub 저장소 Secrets에서 자동 주입됨)
# =====================================================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
COUPANG_PARTNER_TAG = os.environ.get("COUPANG_PARTNER_TAG", "")
SITE_TITLE = os.environ.get("SITE_TITLE", "내 자동 블로그")

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",  # 워크플로에서 apt로 설치함
    "font.ttf",
]

DOCS_DIR = "docs"
POSTS_DIR = os.path.join(DOCS_DIR, "posts")
POSTS_JSON = os.path.join(DOCS_DIR, "posts.json")
QUEUE_FILE = "keywords_queue.json"

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.0-flash:generateContent?key={api_key}"
)

SYSTEM_PROMPT = """당신은 한국어 SEO 블로그 콘텐츠 작가입니다. 아래 규칙을 지켜 작성하세요:
1. 제목은 검색 의도를 반영하되 과장/낚시성 표현은 피한다.
2. 소제목(H2)을 4~6개 사용해 구조화한다.
3. 확인되지 않은 구체적 수치·통계를 지어내지 않는다.
4. 글자 수는 1500~2200자 내외.
5. 자연스러운 위치에 제품 추천 문맥을 1곳 만든다 (실제 링크는 넣지 않음).
6. 출력은 반드시 아래 JSON 형식만 반환한다. 다른 설명, 코드블록 기호(```) 없이 순수 JSON만 출력한다:
{"title": "...", "html_body": "...", "meta_description": "..."}
html_body는 <h2>, <p>, <ul> 등을 사용한 HTML 조각이어야 한다."""

POST_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<meta name="description" content="{meta_description}">
<style>
  body {{ max-width: 720px; margin: 40px auto; padding: 0 20px; font-family: -apple-system, sans-serif; line-height: 1.7; color: #222; }}
  h1 {{ font-size: 1.8em; }}
  h2 {{ font-size: 1.3em; margin-top: 1.5em; border-left: 4px solid #4a90d9; padding-left: 10px; }}
  img.thumb {{ width: 100%; border-radius: 8px; margin-bottom: 20px; }}
  a.back {{ display: inline-block; margin-bottom: 20px; color: #4a90d9; text-decoration: none; }}
</style>
</head>
<body>
<a class="back" href="../index.html">← 목록으로</a>
<img class="thumb" src="../thumbs/{thumb_filename}" alt="{title}">
<h1>{title}</h1>
<p style="color:#888;font-size:0.9em;">{date}</p>
{html_body}
</body>
</html>
"""

INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{site_title}</title>
<style>
  body {{ max-width: 760px; margin: 40px auto; padding: 0 20px; font-family: -apple-system, sans-serif; }}
  h1 {{ font-size: 1.8em; }}
  ul {{ list-style: none; padding: 0; }}
  li {{ margin: 18px 0; }}
  a {{ color: #222; text-decoration: none; }}
  a:hover {{ color: #4a90d9; }}
  img {{ width: 100%; border-radius: 8px; display:block; margin-bottom: 8px; }}
  .date {{ color: #999; font-size: 0.85em; }}
</style>
</head>
<body>
<h1>{site_title}</h1>
<ul>
{items}
</ul>
</body>
</html>
"""

GEMINI_GRADIENT_COLORS = [(66, 133, 244), (156, 39, 176), (234, 67, 121)]
THUMB_SIZE = (1280, 720)


def slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text).strip()
    return re.sub(r"[\s]+", "-", text) or "post"


def get_title_from_args_or_queue() -> str:
    """실행 인자로 받은 제목이 있으면 그걸 쓰고, 없으면 큐에서 하나 꺼냅니다."""
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
    resp = requests.post(url, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise ValueError(f"Gemini 응답 형식이 예상과 다릅니다: {json.dumps(data, ensure_ascii=False)[:400]}")

    cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        article = json.loads(cleaned)
    except json.JSONDecodeError:
        raise ValueError(f"AI 응답을 JSON으로 해석하지 못했습니다. 원본:\n{text[:500]}")

    article["keyword"] = title
    return article


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


def generate_thumbnail(title: str, output_path: str) -> None:
    img = _make_gradient_background(THUMB_SIZE, GEMINI_GRADIENT_COLORS)
    draw = ImageDraw.Draw(img)
    font = _load_font(72)
    lines = textwrap.wrap(title, width=14)[:3]

    heights = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        heights.append(bbox[3] - bbox[1])
    total_h = sum(heights) + (len(lines) - 1) * 20
    y = (THUMB_SIZE[1] - total_h) / 2

    for line, lh in zip(lines, heights):
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (THUMB_SIZE[0] - (bbox[2] - bbox[0])) / 2
        draw.text((x + 4, y + 4), line, font=font, fill=(0, 0, 0))
        draw.text((x, y), line, font=font, fill=(255, 255, 255))
        y += lh + 20

    img.save(output_path, quality=90)


def add_coupang_markup(article: dict) -> dict:
    import urllib.parse
    keyword = article["keyword"]
    search_url = f"https://www.coupang.com/np/search?q={urllib.parse.quote(keyword)}"
    if COUPANG_PARTNER_TAG:
        search_url += f"&lptag={COUPANG_PARTNER_TAG}"

    extra_html = (
        f'<h2>관련 추천 상품</h2>'
        f'<p><a href="{search_url}" target="_blank" rel="nofollow sponsored">{keyword} 관련 인기 상품 보러가기</a></p>'
        '<p style="font-size:0.85em;color:#888;">이 포스팅은 쿠팡 파트너스 활동의 일환으로, '
        '이에 따른 일정액의 수수료를 제공받습니다.</p>'
    )
    article["html_body"] += extra_html
    return article


def save_post(article: dict) -> dict:
    os.makedirs(POSTS_DIR, exist_ok=True)
    os.makedirs(os.path.join(DOCS_DIR, "thumbs"), exist_ok=True)

    slug = slugify(article["keyword"])
    today = datetime.now().strftime("%Y-%m-%d")
    thumb_filename = f"{slug}-{today}.jpg"
    post_filename = f"{slug}-{today}.html"

    generate_thumbnail(article["title"], os.path.join(DOCS_DIR, "thumbs", thumb_filename))

    html = POST_TEMPLATE.format(
        title=article["title"],
        meta_description=article.get("meta_description", ""),
        date=today,
        html_body=article["html_body"],
        thumb_filename=thumb_filename,
    )
    with open(os.path.join(POSTS_DIR, post_filename), "w", encoding="utf-8") as f:
        f.write(html)

    return {"title": article["title"], "file": f"posts/{post_filename}", "thumb": f"thumbs/{thumb_filename}", "date": today}


def update_index(new_post: dict) -> None:
    os.makedirs(DOCS_DIR, exist_ok=True)
    posts = []
    if os.path.exists(POSTS_JSON):
        with open(POSTS_JSON, "r", encoding="utf-8") as f:
            posts = json.load(f)

    posts.insert(0, new_post)
    with open(POSTS_JSON, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)

    items = "\n".join(
        f'<li><a href="{p["file"]}"><img src="{p["thumb"]}" alt="{p["title"]}">{p["title"]}</a>'
        f'<div class="date">{p["date"]}</div></li>'
        for p in posts
    )
    with open(os.path.join(DOCS_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(INDEX_TEMPLATE.format(site_title=SITE_TITLE, items=items))


def run():
    title = get_title_from_args_or_queue()
    print(f"[처리 시작] 제목: {title}")

    article = generate_article(title)
    print(f"  → 글 생성 완료: {article['title']}")

    article = add_coupang_markup(article)
    post_meta = save_post(article)
    update_index(post_meta)

    print(f"  → 저장 완료: docs/{post_meta['file']}, docs/{post_meta['thumb']}")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        print(f"[오류] {e}")
        sys.exit(1)
