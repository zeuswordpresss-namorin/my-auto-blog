import asyncio
import os
import re
import edge_tts

# [경로 설정]
# 기존 generate_post.py가 포스트를 생성하는 경로와 동일하게 맞춰야 합니다.
TARGET_POST_PATH = "docs/index.html" 
AUDIO_OUTPUT_PATH = "docs/announcer_reading.mp3"
AUDIO_REL_URL = "./announcer_reading.mp3"

def extract_text_from_html(html_content):
    """
    HTML 파일 내용에서 TTS 음성 합성에 사용할 순수 본문 텍스트만 추출합니다.
    tags 제거용 간단한 정규식을 사용합니다.
    """
    # HTML 태그들을 제거하여 순수 텍스트만 남김
    clean_text = re.sub(r'<[^>]+>', ' ', html_content)
    # 공백 정리
    clean_text = " ".join(clean_text.split())
    return clean_text

def inject_player_markup(html_content, title_placeholder="아나운서 리딩 포스트"):
    """
    기존 블로그 HTML 내용의 <body> 시작 지점 바로 뒤에 모바일 최적화 플레이어 UI를 주입합니다.
    """
    player_html = f"""
    <!-- 모바일 및 웹 터치 최적화 오디오 플레이어 UI 주입 시작 -->
    <div class="player-interface" style="
        display: flex; align-items: center; background: #e9ecef;
        padding: 12px 18px; border-radius: 30px; margin: 20px 0;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    ">
        <button id="ui-ctrl-btn" class="toggle-control-btn" onclick="triggerAudioStream()" style="
            width: 48px; height: 48px; background-color: #007bff; border: none;
            color: #ffffff; border-radius: 50%; cursor: pointer; font-size: 16px;
            display: flex; align-items: center; justify-content: center;
            box-shadow: 0 3px 6px rgba(0,123,255,0.2);
            transition: all 0.2s; -webkit-tap-highlight-color: transparent;
        ">▶</button>
        <div class="player-status-block" style="margin-left: 15px; text-align: left;">
            <p id="ui-status-text" class="main-status-label" style="margin: 0; font-size: 14px; font-weight: 600; color: #212529;">아나운서 리딩 듣기</p>
            <p class="sub-status-label" style="margin: 0; font-size: 11px; color: #868e96; margin-top: 2px;">버튼을 터치하여 음성을 켜고 끌 수 있습니다. (ON/OFF)</p>
        </div>
    </div>
    <audio id="core-audio-engine" src="{AUDIO_REL_URL}"></audio>
    
    <script>
    function triggerAudioStream() {{
        const audio = document.getElementById('core-audio-engine');
        const btn = document.getElementById('ui-ctrl-btn');
        const txt = document.getElementById('ui-status-text');
        if (audio.paused) {{
            audio.play(); btn.innerHTML = '⏸'; btn.style.backgroundColor = '#dc3545';
            txt.innerText = '아나운서 음성 리딩 중...';
        }} else {{
            audio.pause(); btn.innerHTML = '▶'; btn.style.backgroundColor = '#007bff';
            txt.innerText = '아나운서 리딩 일시정지';
        }}
    }}
    document.getElementById('core-audio-engine').addEventListener('ended', function() {{
        document.getElementById('ui-ctrl-btn').innerHTML = '▶';
        document.getElementById('ui-ctrl-btn').style.backgroundColor = '#007bff';
        document.getElementById('ui-status-text').innerText = '아나운서 리딩 듣기';
    }});
    </script>
    <!-- 모바일 및 웹 터치 최적화 오디오 플레이어 UI 주입 끝 -->
    """
    
    # <body> 태그 뒤나 혹은 파일 맨 앞에 플레이어 삽입
    if "<body>" in html_content:
        return html_content.replace("<body>", f"<body>\n{player_html}")
    else:
        return player_html + "\n" + html_content

async def main():
    print("[시스템] 포스트 파일 연동 오디오 주입 파이프라인 가동...")

    # 1. 먼저 generate_post.py를 강제로 실행하여 블로그 원본 포스트(HTML 등)를 생성하게 만듭니다.
    print("[1단계] generate_post.py 실행 호출 중...")
    # 저장소 환경에 맞게 원본 생성 코드를 실행시킵니다.
    os.system("python generate_post.py")

    # 2. generate_post.py가 생성한 최종 결과물 파일이 존재하는지 검증합니다.
    if not os.path.exists(TARGET_POST_PATH):
        print(f"[오류] {TARGET_POST_PATH} 파일이 생성되지 않았습니다. 경로를 확인해 주세요.")
        return

    # 3. 생성된 블로그 포스트의 텍스트 본문 읽기 및 추출
    with open(TARGET_POST_PATH, "r", encoding="utf-8") as f:
        original_html = f.read()
        
    post_text = extract_text_from_html(original_html)
    print(f"[2단계] 파일로부터 텍스트 추출 완료 ({len(post_text)}자)")

    # 4. 추출된 본문 텍스트에 기반한 아나운서 TTS 생성
    print("[3단계] 추출 문장 기반 차분한 아나운서 TTS 생성 중...")
    voice = "ko-KR-SunHiNeural"
    rate = "-10%"
    
    communicate = edge_tts.Communicate(post_text, voice, rate=rate)
    await communicate.save(AUDIO_OUTPUT_PATH)
    print(f"[성공] 아나운서 MP3 파일 매칭 저장 완료: {AUDIO_OUTPUT_PATH}")

    # 5. 기존 HTML 포스트 파일 내부에 오디오 플레이어 스크립트 및 UI 주입
    updated_html = inject_player_markup(original_html)
    
    with open(TARGET_POST_PATH, "w", encoding="utf-8") as f:
        f.write(updated_html)
    print(f"[성공] 기존 포스트 파일 내부에 모바일 플레이어 UI 결합 완료: {TARGET_POST_PATH}")

if __name__ == "__main__":
    asyncio.run(main())
