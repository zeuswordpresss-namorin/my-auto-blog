# -*- coding: utf-8 -*-
"""
이미 발행된 옛날 글들을 전부 최신 템플릿(번역위젯 아이콘, 이전/최신글 네비게이션,
반응형 CSS, 픽셀단위로 안 넘치는 썸네일 등)으로 다시 감싸서 업그레이드합니다.

AI를 다시 호출하지 않습니다 (비용 없음). 기존 글의 실제 내용(본문)은 그대로 유지하고,
겉모습(템플릿/썸네일)만 지금 최신 코드 기준으로 다시 만듭니다.

동작:
  1. docs/posts.json에 있는 모든 글을 순회
  2. 각 글의 기존 HTML 파일에서 본문 내용과 meta_description을 추출
  3. 썸네일을 최신 로직(픽셀 단위 자동맞춤 폰트)으로 재생성
  4. 최신 POST_TEMPLATE으로 다시 감싸서 같은 파일명으로 덮어씀 (URL은 그대로라 안 깨짐)

실행: python regenerate_all_posts.py
주의: generate_post.py와 같은 폴더에서 실행해야 합니다 (그 안의 함수를 그대로 재사용합니다).
"""

import json
import os
import re

import generate_post as gp


def extract_old_content(html: str):
    """예전에 생성된 post HTML 파일에서 제목/설명/본문을 최대한 안전하게 추출합니다."""
    title_m = re.search(r"<title>(.*?)</title>", html, re.S)
    title = title_m.group(1).split(" - ")[0].strip() if title_m else ""

    desc_m = re.search(r'<meta name="description" content="(.*?)">', html, re.S)
    meta_description = desc_m.group(1) if desc_m else ""

    # <p class="meta">날짜</p> 바로 다음부터, post-nav/related 섹션(또는 body 끝) 전까지가 본문
    body_m = re.search(
        r'<p class="meta">.*?</p>(.*?)(?=<div class="post-nav">|<div class="related">|\s*</div>\s*</body>)',
        html, re.S,
    )
    html_body = body_m.group(1).strip() if body_m else ""

    # FAQ 아코디언(details/summary)이 있으면 질문/답변 쌍을 다시 추출해서 구조화 스키마 복원
    faq_items = [
        {"question": q.strip(), "answer": a.strip()}
        for q, a in re.findall(
            r'<summary[^>]*>Q\d+\.\s*(.*?)</summary>\s*<p[^>]*>A\.\s*(.*?)</p>', html_body, re.S,
        )
    ]
    if not faq_items:
        # 예전(구버전) 카드형 FAQ 구조도 대비 (하위 호환)
        faq_items = [
            {"question": q.strip(), "answer": a.strip()}
            for q, a in re.findall(
                r'>Q\d+\.\s*(.*?)</p><p[^>]*>A\.\s*(.*?)</p>', html_body, re.S,
            )
        ]
    schema_type = "FAQPage" if faq_items else "Article"
    return title, meta_description, html_body, schema_type, faq_items


def rerender_post(post_meta: dict, article: dict) -> None:
    """추출한 내용을 최신 템플릿/썸네일로 다시 렌더링해서 같은 파일에 덮어씁니다."""
    theme = gp.get_theme(post_meta.get("category", "라이프스타일"))
    post_filename = os.path.basename(post_meta["file"])
    thumb_filename = os.path.basename(post_meta["thumb"])

    # 썸네일을 최신 로직(픽셀 단위 자동맞춤)으로 재생성
    gp.generate_thumbnail(
        article["title"],
        os.path.join(gp.DOCS_DIR, "thumbs", thumb_filename),
        theme,
        post_meta.get("category", "라이프스타일"),
    )

    post_url = f"{gp.SITE_URL}/posts/{post_filename}" if gp.SITE_URL else f"posts/{post_filename}"
    thumb_url = f"{gp.SITE_URL}/thumbs/{thumb_filename}" if gp.SITE_URL else f"../thumbs/{thumb_filename}"

    json_ld = gp.build_json_ld(article, post_url, thumb_url, post_meta["date"])
    related_html = gp._build_related_html(exclude_slug=post_meta["file"])
    post_nav = gp._build_post_nav_html()
    decor_html = gp.build_decor_html(theme, seed=post_filename)

    html = gp.POST_TEMPLATE.format(
        title=article["title"],
        meta_description=article["meta_description"],
        date=post_meta["date"],
        html_body=article["html_body"],
        thumb_filename=thumb_filename,
        canonical_url=post_url,
        thumb_url=thumb_url,
        json_ld=json_ld,
        ga_snippet=gp._ga_snippet(),
        adsense_snippet=gp._adsense_snippet(),
        font=theme["font"],
        font_family=gp._font_family_name(theme["font"]),
        accent=theme["accent"],
        badge=theme["badge"],
        related_html=related_html,
        post_nav=post_nav,
        decor_html=decor_html,
        bottom_ad=gp._manual_ad_unit(),
        search_console_meta=gp._search_console_meta(),
        translate_widget=gp._translate_widget(),
    )
    with open(os.path.join(gp.POSTS_DIR, post_filename), "w", encoding="utf-8") as f:
        f.write(html)


def run():
    if not os.path.exists(gp.POSTS_JSON):
        print("posts.json이 없습니다. 먼저 글을 하나 이상 발행해주세요.")
        return
    with open(gp.POSTS_JSON, "r", encoding="utf-8") as f:
        posts = json.load(f)

    success, failed = 0, 0
    for post_meta in posts:
        post_path = os.path.join(gp.POSTS_DIR, os.path.basename(post_meta["file"]))
        if not os.path.exists(post_path):
            print(f"  → 건너뜀 (파일 없음): {post_meta['file']}")
            failed += 1
            continue
        try:
            with open(post_path, "r", encoding="utf-8") as f:
                old_html = f.read()
            title, meta_description, html_body, schema_type, faq_items = extract_old_content(old_html)
            if not html_body:
                print(f"  → 건너뜀 (본문 추출 실패, 수동 확인 필요): {post_meta['file']}")
                failed += 1
                continue

            article = {
                "title": title or post_meta["title"],
                "meta_description": meta_description,
                "html_body": html_body,
                "schema_type": schema_type,
                "faq_items": faq_items,
                "category": post_meta.get("category", "라이프스타일"),
            }
            rerender_post(post_meta, article)
            print(f"  → 업그레이드 완료: {post_meta['file']}")
            success += 1
        except Exception as e:
            print(f"  → 실패: {post_meta['file']} ({e})")
            failed += 1

    print(f"\n완료: 성공 {success}건 / 실패 {failed}건")
    if failed:
        print("실패/건너뜀 항목은 기존 상태 그대로 유지됩니다 (안전하게 원본 보존).")


if __name__ == "__main__":
    run()

