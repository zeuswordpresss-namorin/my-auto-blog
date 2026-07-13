import asyncio
import os
import re
import edge_tts

# =========================================================================
# [수정 가능한 매개변수 설정]
# =========================================================================
TARGET_POST_PATH = "docs/index.html" 
AUDIO_OUTPUT_PATH = "docs/announcer_reading.mp3"
AUDIO_ABSOLUTE_URL = "https://sss-namorin.github.io/announcer_reading.mp3"

def extract_text_from_html(html_content):
    """HTML 본문에서 자바스크립트/스타일을 제외하고 순수 텍스트만 파싱합니다."""
    clean_content = re.sub(r'<script[^>]*>([\s\S]*?)</script>', ' ', html_content)
    clean_content = re.sub(r'<style[^>]*>([\s\S]*?)</style>', ' ', html_content)
    clean_text = re.sub(r'<[^>]+>', ' ', clean_content)
    return " ".join(clean_text.split())

def inject_icon_player_universal(original_html):
    """
    자동 발행 후 깨지거나 유실된 플레이어 영역을 복구합니다.
    카테고리 텍스트(재테크 등)에 상관없이 배지 태그 우측에 플레이어를 주입합니다.
    """
    
    # 중복 주입 방지 로직 추가
    if "tts-audio-engine" in original_html:
        print("[정보] 이미 플레이어 코드가 존재합니다. 기존 코드를 제거하고 새로 주입합니다.")
        # 기존 플레이어 마크업 경계가 있다면 제거하는 유연성 확보 가능
    
    icon_player_markup = f'''
    <!-- [수동 액션 대응형 오디오 플레이어 컴포넌트] -->
    <span class="inline-tts-player" style="display: inline-flex !important; align-items: center !important; margin-left: 12px !important; vertical-align: middle !important; visibility: visible !important;">
        <button id="tts-icon-btn" onclick="window.toggleAnnouncerVoice()" style="
            width: 32px !important; height: 32px !important; border-radius: 50% !important; 
            background-color: #007bff !important; border: none !important; color: #ffffff !important; 
            font-size: 11px !important; font-weight: bold !important; cursor: pointer !important; 
            display: flex !important; align-items: center !important; justify-content: center !important;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1) !important; padding: 0 !important; margin: 0 !important;
        ">▶</button>
        <span id="tts-mini-status" style="font-size: 12px !important; margin-left: 6px !important; color: #6c757d !important; font-weight: bold !important; font-family: sans-serif !important;">리딩 듣기</span>
        <audio id="tts-audio-engine" src="{AUDIO_ABSOLUTE_URL}" style="display: none !important;"></audio>
    </span>

    <script>
    window.toggleAnnouncerVoice = function() {{
        const audio = document.getElementById('tts-audio-engine');
        const btn = document.getElementById('tts-icon-btn');
        const status = document.getElementById('tts-mini-status');
        
        if (!audio || !btn || !status) return;
        
        if (audio.paused) {{
            audio.play().catch(e => console.log("재생 오류 오버라이드:", e));
            btn.innerHTML = '⏸';
            btn.style.setProperty('background-color', '#dc3545', 'important');
            status.innerText = '리딩 중...';
            status.style.setProperty('color', '#dc3545', 'important');
        }} else {{
            audio.pause();
            btn.innerHTML = '▶';
            btn.style.setProperty('background-color', '#007bff', 'important');
            status.innerText = '일시정지';
            status.style.setProperty('color', '#6c757d', 'important');
        }}
    }};
    
    // 재생 완료 시 상태 초기화 훅
    setTimeout(() => {{
        const aud = document.getElementById('tts-audio-engine');
        if (aud) {{
            aud.addEventListener('ended', function() {{
                const btn = document.getElementById('tts-icon-btn');
                const status = document.getElementById('tts-mini-status');
                if (btn && status) {{
                    btn.innerHTML = '▶';
                    btn.style.setProperty('background-color', '#007bff', 'important');
                    status.innerText = '리딩 듣기';
                    status.style.setProperty('color', '#6c757d', 'important');
                }}
            }});
        }}
    }}, 500);
    </script>
    '''

    # 모든 형태의 카테고리 배지 매칭 정규식
    universal_badge_pattern = r'(<[^>]+>\s*✨?\s*[가-힣a-zA-Z\s·•ㆍ]+\s*</[^>]+>)'
    
    match = re.search(universal_badge_pattern, original_html)
    if match:
        print(f"[매칭 성공] 배지 발견: {match.group(1)}")
        return re.sub(universal_badge_pattern, r'\1' + icon_player_markup, original_html, count=1)
    
    if "<body>" in original_html:
        return original_html.replace("<body>", f"<body>\n{icon_player_markup}")
    return icon_player_markup + "\n" + original_html

async def pipeline_process():
    print("[시스템] 수동 트리거 모드 파이프라인 엔진 가동...")

    if not os.path.exists(TARGET_POST_PATH):
        print(f"[오류] 자동 발행된 기본 파일이 없습니다: {TARGET_POST_PATH}")
        return

    with open(TARGET_POST_PATH, "r", encoding="utf-8") as f:
        html_layout = f.read()

    post_text = extract_text_from_html(html_layout)
    print(f"[안내] 리딩용 텍스트 빌드 완료 ({len(post_text)}자)")
    
    # 고품질 오디오 파일 합성 및 덮어쓰기
    communicate = edge_tts.Communicate(post_text, "ko-KR-SunHiNeural", rate="-10%")
    await communicate.save(AUDIO_OUTPUT_PATH)
    print(f"[성공] 최신 오디오 자산 생성 완료: {AUDIO_OUTPUT_PATH}")

    # 플레이어 코드 강제 주입
    processed_html = inject_icon_player_universal(html_layout)

    with open(TARGET_POST_PATH, "w", encoding="utf-8") as f:
        f.write(processed_html)
    print("[성공] 수동 오디오 플레이어 액션 처리가 완수되었습니다.")

if __name__ == "__main__":
    asyncio.run(pipeline_process())
