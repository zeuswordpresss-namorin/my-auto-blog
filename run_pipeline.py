import asyncio
import os
import edge_tts

# [경로 및 출력 설정]
OUTPUT_DIR = "docs"
AUDIO_FILENAME = "announcer_reading.mp3"
HTML_FILENAME = "index.html"

async def build_voice_and_html(title, content):
    """
    generate_post.py 등에서 생성 완료된 문장을 전달받아 
    TTS 오디오 생성 및 모바일 최적화 플레이어 HTML을 빌드하는 핵심 함수입니다.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    audio_path = os.path.join(OUTPUT_DIR, AUDIO_FILENAME)
    html_path = os.path.join(OUTPUT_DIR, HTML_FILENAME)

    print(f"[파이프라인] 추출된 문장 기반 TTS 오디오 합성 시작...")
    
    # 차분하고 신뢰감 있는 한국어 여성 아나운서 음성 설정 및 10% 감속
    voice = "ko-KR-SunHiNeural"
    rate = "-10%"
    
    communicate = edge_tts.Communicate(content, voice, rate=rate)
    await communicate.save(audio_path)
    print(f"[성공] 아나운서 MP3 저장 완료: {audio_path}")

    # 모바일 및 웹 터치 최적화 UI 빌드
    html_layout = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        *, *::before, *::after {{ box-sizing: border-box; }}
        body {{
            margin: 0; padding: 20px; background-color: #f8f9fa; color: #333;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        }}
        .wrapper {{
            max-width: 650px; margin: 0 auto; background: #ffffff;
            padding: 25px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        }}
        h1 {{ font-size: 1.4rem; margin-top: 0; color: #111; line-height: 1.4; }}
        .player-interface {{
            display: flex; align-items: center; background: #e9ecef;
            padding: 12px 18px; border-radius: 30px; margin: 20px 0;
        }}
        .toggle-control-btn {{
            width: 48px; height: 48px; background-color: #007bff; border: none;
            color: #ffffff; border-radius: 50%; cursor: pointer; font-size: 16px;
            display: flex; align-items: center; justify-content: center;
            box-shadow: 0 3px 6px rgba(0,123,255,0.2);
            transition: all 0.2s; -webkit-tap-highlight-color: transparent;
        }}
        .player-status-block {{ margin-left: 15px; }}
        .main-status-label {{ margin: 0; font-size: 14px; font-weight: 600; color: #212529; }}
        .sub-status-label {{ margin: 0; font-size: 11px; color: #868e96; margin-top: 2px; }}
        .text-content-area {{ font-size: 16px; line-height: 1.8; color: #495057; }}
    </style>
</head>
<body>
<div class="wrapper">
    <h1>{title}</h1>
    <div class="player-interface">
        <button id="ui-ctrl-btn" class="toggle-control-btn" onclick="triggerAudioStream()">▶</button>
        <div class="player-status-block">
            <p id="ui-status-text" class="main-status-label">아나운서 리딩 듣기</p>
            <p class="sub-status-label">버튼을 터치하여 음성을 켜고 끌 수 있습니다. (ON/OFF)</p>
        </div>
    </div>
    <audio id="core-audio-engine" src="./{AUDIO_FILENAME}"></audio>
    <div class="text-content-area"><p>{content}</p></div>
</div>
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
</body>
</html>
"""
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_layout)
    print(f"[성공] 모바일 웹 화면 최적화 index.html 빌드 완료!")

async def main():
    print("[시스템] 파이프라인 가동: generate_post.py 연동 프로세스를 시작합니다.")
    
    # 1. 기존 가동 스크립트(generate_post)로부터 생성 로직을 동적으로 수행하거나 결과 호출
    # 여기서는 기존 소스코드 구조의 매커니즘을 그대로 이어받도록 설계되었습니다.
    # 예시로 generate_post가 만들어낸 최종 커스텀 콘텐츠 문장 변수를 가져옵니다.
    generated_title = "자동 생성 프로세스가 제어하는 스마트 홈 기기"
    generated_content = "안녕하세요. 오늘 generate 로직을 통해 추출된 문장 기반 포스팅입니다. 무선 네트워크와 연동된 스마트 가전은 우리의 삶을 더욱 풍요롭게 만들어 줍니다."

    # 2. 문장 추출 완료 후 곧바로 연쇄적인 오디오 및 웹페이지 빌드 워크플로우 실행
    await build_voice_and_html(generated_title, generated_content)

if __name__ == "__main__":
    asyncio.run(main())

