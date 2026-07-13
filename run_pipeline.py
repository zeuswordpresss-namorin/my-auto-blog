import asyncio
import os
import re
import edge_tts

# =========================================================================
# [수정 가능한 매개변수 및 절대 경로 설정]
# =========================================================================
TARGET_POST_PATH = "docs/index.html" 
AUDIO_OUTPUT_PATH = "docs/announcer_reading.mp3"

# [중요] 구글 블로그(Blogger) 연동을 위해 자신의 깃허브 도메인 절대 경로 주소를 입력해 주세요.
# 예: "https://username.github.io/repository-name/announcer_reading.mp3"
# 여기서는 깃허브 페이지 배포 표준 주소 형식으로 지정합니다.
AUDIO_ABSOLUTE_URL = "https://zeuswordpress-namorin.github.io/my-auto-blog/announcer_reading.mp3"

def extract_text_from_html(html_content):
    """HTML 본문에서 자바스크립트와 스타일을 제외하고 오디오용 순수 텍스트만 파싱합니다."""
    clean_content = re.sub(r'<script[^>]*>([\s\S]*?)</script>', ' ', html_content)
    clean_content = re.sub(r'<style[^>]*>([\s\S]*?)</style>', ' ', clean_content)
    clean_text = re.sub(r'<[^>]+>', ' ', clean_content)
    return " ".join(clean_text.split())

def inject_google_blog_player(original_html):
    """
    [추론 과정 및 동작 수정]
    구글 블로그의 보안 검열을 우회하기 위해, 스크립트 오작동 시에도 
    모바일에서 무조건 기본 플레이어가 렌더링되도록 HTML 표준 양식을 주입합니다.
    기존 디자인 테마를 해치지 않고 <body> 태그 바로 아래에 결합합니다.
    """
    
    player_markup = f"""
    <!-- 구글 블로그 및 웹 최적화 아나운서 TTS 플레이어 시작 -->
    <div class="voice-player-widget" style="
        max-width: 100%; margin: 20px auto; padding: 15px; 
        background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 16px; 
        box-shadow: 0 4px 6px rgba(0,0,0,0.02);
        font-family: -apple-system, BlinkMacSystemFont, sans-serif;
    ">
        <div style="display: flex; align-items: center; gap: 15px; margin-bottom: 10px;">
            <button id="tts-ctrl-btn" onclick="toggleAnnouncerVoice()" style="
                width: 46px; height: 46px; border-radius: 50%; 
                background-color: #007bff; border: none; color: #ffffff; 
                font-size: 16px; font-weight: bold; cursor: pointer;
                display: flex; align-items: center; justify-content: center;
                box-shadow: 0 2px 5px rgba(0,123,255,0.3);
                -webkit-tap-highlight-color: transparent;
            ">▶</button>
            <div style="text-align: left;">
                <p id="tts-status-title" style="margin: 0; font-size: 14px; font-weight: bold; color: #212529;">아나운서 리딩 듣기</p>
                <span style="font-size: 11px; color: #6c757d;">터치 시 목소리 ON / OFF (크로스 브라우징 지원)</span>
            </div>
        </div>
        
        <!-- 구글 블로그 보안 정책 우회용 표준 브라우저 오디오 바 (스크립트 차단 대비용 내장형) -->
        <audio id="tts-audio-engine" src="{AUDIO_ABSOLUTE_URL}" controls style="width: 100%; height: 32px; margin-top: 5px;"></audio>
    </div>

    <script>
    function toggleAnnouncerVoice() {{
        const audio = document.getElementById('tts-audio-engine');
        const btn = document.getElementById('tts-ctrl-btn');
        const txt = document.getElementById('tts-status-title');
        
        if (audio.paused) {{
            audio.play();
            btn.innerHTML = '⏸';
            btn.style.backgroundColor = '#dc3545';
            txt.innerText = '아나운서 음성 리딩 중...';
        }} else {{
            audio.pause();
            btn.innerHTML = '▶';
            btn.style.backgroundColor = '#007bff';
            txt.innerText = '아나운서 리딩 일시정지';
        }}
    }}
    
    // 오디오 종료 시 재생 버튼 상태 복구 동기화
    document.getElementById('tts-audio-engine').addEventListener('ended', function() {{
        document.getElementById('tts-ctrl-btn').innerHTML = '▶';
        document.getElementById('tts-ctrl-btn').style.backgroundColor = '#007bff';
        document.getElementById('tts-status-title').innerText = '아나운서 리딩 듣기';
    }});
    </script>
    <!-- 구글 블로그 및 웹 최적화 아나운서 TTS 플레이어 끝 -->
    """

    # 원본 HTML 레이아웃 서식을 완전히 유지한 채 플레이어만 특정 위치에 주입
    if "<body>" in original_html:
        return original_html.replace("<body>", f"<body>\n{player_markup}")
    return player_markup + "\n" + original_html

async def pipeline_process():
    print("[시스템] 디자인 보존형 및 구글 블로그 호환 파이프라인 가동...")

    # 1단계: 기존 본문 빌더 프로그램을 호출하여 원본 생성
    os.system("python generate_post.py")

    if not os.path.exists(TARGET_POST_PATH):
        print(f"[오류] 원본 파일 경로를 찾을 수 없습니다: {TARGET_POST_PATH}")
        return

    # 2단계: 기존 파일의 디자인 서식 코드를 메모리에 복사 (덮어쓰기 방지)
    with open(TARGET_POST_PATH, "r", encoding="utf-8") as f:
        original_design_html = f.read()

    # 3단계: 텍스트 추출 및 부드러운 아나운서 음성 합성
    post_text = extract_text_from_html(original_design_html)
    print(f"[알림] 본문 텍스트 추출 성공 ({len(post_text)}자)")

    print("[알림] edge-tts 아나운서 음성 파일 제작 중...")
    communicate = edge_tts.Communicate(post_text, "ko-KR-SunHiNeural", rate="-10%")
    await communicate.save(AUDIO_OUTPUT_PATH)
    print(f"[성공] MP3 파일 빌드 및 docs 저장 완료: {AUDIO_OUTPUT_PATH}")

    # 4단계: 기존 디자인 구조에 구글 블로그 검열을 우회하는 플레이어 레이아웃 병합
    final_combined_html = inject_google_blog_player(original_design_html)

    # 5단계: 최종 결합된 전체 내용으로 파일 교체
    with open(TARGET_POST_PATH, "w", encoding="utf-8") as f:
        f.write(final_combined_html)
    print(f"[성공] 원본 디자인 복구 및 플레이어 통합 교체 완료!")

if __name__ == "__main__":
    asyncio.run(pipeline_process())
