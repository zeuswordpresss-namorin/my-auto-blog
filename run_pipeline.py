import asyncio
import os
import re
import edge_tts

# =========================================================================
# [설정 매개변수 및 절대 경로 설정]
# =========================================================================
# 폰에서 실행 시 및 GitHub Actions 환경 모두 호환되는 상대/절대 경로 지정
TARGET_POST_PATH = "docs/index.html" 
AUDIO_OUTPUT_PATH = "docs/announcer_reading.mp3"

# GitHub Pages 및 구글 블로그(Blogger)에서 크로스 오리진 제한 없이 완벽 로드되는 절대 주소
AUDIO_ABSOLUTE_URL = "https://sss-namorin.github.io/announcer_reading.mp3"

def extract_text_from_html(html_content):
    """HTML 본문에서 자바스크립트와 스타일을 제외하고 오디오용 순수 텍스트만 파싱합니다."""
    clean_content = re.sub(r'<script[^>]*>([\s\S]*?)</script>', ' ', html_content)
    clean_content = re.sub(r'<style[^>]*>([\s\S]*?)</style>', ' ', clean_content)
    clean_text = re.sub(r'<[^>]+>', ' ', clean_content)
    return " ".join(clean_text.split())

def inject_icon_player_beside_badge(original_html):
    """
    [추론 및 UI 구현]
    구글 블로그(Blogger)의 엄격한 스크립트 검열을 우회하고 모바일 화면 최적화를 위해,
    카테고리 배지 바로 옆에 깔끔한 오디오 인라인 재생/일시정지 아이콘을 안전하게 결합합니다.
    """
    
    icon_player_markup = f'''
    <!-- 아나운서 TTS 본문 내장형 미니 플레이어 시작 (GitHub Pages & Blogger 호환) -->
    <span class="inline-tts-player" style="display: inline-flex; align-items: center; margin-left: 10px; vertical-align: middle;">
        <button id="tts-icon-btn" onclick="toggleAnnouncerVoice()" style="
            width: 32px; height: 32px; border-radius: 50%; 
            background-color: #007bff; border: none; color: #ffffff; 
            font-size: 12px; cursor: pointer; display: flex; align-items: center; justify-content: center;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1); -webkit-tap-highlight-color: transparent;
            transition: all 0.2s ease;
        ">▶</button>
        <span id="tts-mini-status" style="font-size: 12px; margin-left: 6px; color: #6c757d; font-weight: 500;">리딩 듣기</span>
        <audio id="tts-audio-engine" src="{AUDIO_ABSOLUTE_URL}" style="display: none;"></audio>
    </span>

    <script>
    function toggleAnnouncerVoice() {{
        const audio = document.getElementById('tts-audio-engine');
        const btn = document.getElementById('tts-icon-btn');
        const status = document.getElementById('tts-mini-status');
        
        if (audio.paused) {{
            audio.play().catch(function(error) {{
                console.log("Autoplay / Play blocked:", error);
            }});
            btn.innerHTML = '⏸';
            btn.style.backgroundColor = '#dc3545';
            status.innerText = '리딩 중...';
            status.style.color = '#dc3545';
        }} else {{
            audio.pause();
            btn.innerHTML = '▶';
            btn.style.backgroundColor = '#007bff';
            status.innerText = '일시정지';
            status.style.color = '#6c757d';
        }}
    }}
    
    document.getElementById('tts-audio-engine').addEventListener('ended', function() {{
        const btn = document.getElementById('tts-icon-btn');
        const status = document.getElementById('tts-mini-status');
        btn.innerHTML = '▶';
        btn.style.backgroundColor = '#007bff';
        status.innerText = '리딩 듣기';
        status.style.color = '#6c757d';
    }});
    </script>
    <!-- 아나운서 TTS 본문 내장형 미니 플레이어 끝 -->
    '''

    # 배지 디자인 패턴 탐색 (클래스명 유연성 및 '라이프스타일' 텍스트 기준 매칭)
    badge_pattern = r'(<[^>]+>\s*✨?\s*라이프스타일\s*</[^>]+>)'
    
    if re.search(badge_pattern, original_html):
        print("[정보] 라이프스타일 배지 위치 탐색 성공. 우측 공간에 아이콘 플레이어를 주입합니다.")
        return re.sub(badge_pattern, r'\1' + icon_player_markup, original_html)
    
    print("[경고] 지정된 배지 서식을 찾지 못했습니다. 본문 최상단에 안전하게 주입합니다.")
    if "<body>" in original_html:
        return original_html.replace("<body>", f"<body>\n{icon_player_markup}")
    return icon_player_markup + "\n" + original_html

async def pipeline_process():
    print("[시스템] 디자인 보존형 및 플랫폼 교차 호환 파이프라인 가동...")

    # 1단계: 기존 본문 빌더 프로그램 실행
    if os.path.exists("generate_post.py"):
        os.system("python generate_post.py")
    else:
        print("[참고] generate_post.py가 없는 단독 테스트 환경입니다. 기존 index.html을 바로 수정합니다.")

    if not os.path.exists(TARGET_POST_PATH):
        print(f"[오류] 원본 파일 경로를 찾을 수 없습니다: {TARGET_POST_PATH}")
        return

    # 2단계: 기존 파일의 레이아웃 코드를 메모리에 로드
    with open(TARGET_POST_PATH, "r", encoding="utf-8") as f:
        original_design_html = f.read()

    # 3단계: 순수 텍스트 오디오 합성
    post_text = extract_text_from_html(original_design_html)
    print(f"[알림] 본문 텍스트 추출 성공 ({len(post_text)}자)")

    print("[알림] edge-tts 아나운서 음성 파일 제작 중...")
    communicate = edge_tts.Communicate(post_text, "ko-KR-SunHiNeural", rate="-10%")
    await communicate.save(AUDIO_OUTPUT_PATH)
    print(f"[성공] MP3 파일 빌드 및 저장 완료: {AUDIO_OUTPUT_PATH}")

    # 4단계: 배지 우측 타겟팅 매핑 주입 수행
    final_combined_html = inject_icon_player_beside_badge(original_design_html)

    # 5단계: 최종 결합된 전체 내용으로 파일 교체
    with open(TARGET_POST_PATH, "w", encoding="utf-8") as f:
        f.write(final_combined_html)
    print(f"[성공] 원본 디자인 보존 및 배지 우측 플레이어 통합 교체 완료!")

if __name__ == "__main__":
    asyncio.run(pipeline_process())
