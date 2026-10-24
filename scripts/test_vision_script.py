import os
import sys
import base64
import subprocess
from pathlib import Path
import requests

sys.stdout.reconfigure(encoding='utf-8')

def analyze_video_visually(video_path: Path):
    cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', str(video_path)]
    dur = float(subprocess.check_output(cmd).decode().strip())
    print(f"Duration: {dur:.2f}s")

    timestamps = [dur * 0.15, dur * 0.40, dur * 0.65, dur * 0.88]
    frame_parts = []
    temp_dir = Path("temp_vis_test")
    temp_dir.mkdir(exist_ok=True)
    
    for idx, ts in enumerate(timestamps):
        frame_file = temp_dir / f"f_{idx}.jpg"
        subprocess.run(['ffmpeg', '-y', '-ss', str(ts), '-i', str(video_path), '-vframes', '1', '-q:v', '2', str(frame_file)], capture_output=True)
        if frame_file.exists():
            b64 = base64.b64encode(frame_file.read_bytes()).decode('utf-8')
            frame_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
            })
    print(f"Extracted {len(frame_parts)} frames")

    prompt = (
        "You are an expert viral video commentator. Look at these 4 sequential frames extracted from a video clip.\n"
        "1. Inspect what is physically happening in these frames step-by-step.\n"
        "2. Write an energetic, witty commentary voiceover (40 to 60 words, ~18 seconds) that narrates and reacts to the EXACT physical events on screen.\n"
        "CRITICAL RULES:\n"
        "- Do NOT write generic clickbait like 'Wait till the end' or 'You won't believe this'.\n"
        "- Describe the specific people, props, actions, and reactions that the viewer actually sees.\n"
        "- Return ONLY valid JSON with this schema:\n"
        "{\n"
        '  "visual_summary": "one sentence describing what happens",\n'
        '  "script": "spoken voiceover narration exactly matching visual actions",\n'
        '  "title": "punchy YouTube shorts title with emojis and #Shorts",\n'
        '  "cyan_keywords": ["KEYWORD1", "KEYWORD2"],\n'
        '  "debate_question": "engaging comment question",\n'
        '  "tags": ["shorts", "tag1", "tag2"]\n'
        "}"
    )

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY must be set in the environment")
    messages = [
        {
            "role": "user",
            "content": [{"type": "text", "text": prompt}] + frame_parts
        }
    ]

    res = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": "google/gemini-3.8-flash",
            "messages": messages,
            "max_tokens": 800,
            "response_format": {"type": "json_object"}
        },
        timeout=40
    )
    print("Status:", res.status_code)
    data = res.json()
    if "choices" in data:
        content = data["choices"][0]["message"]["content"]
        print("RESULT JSON:\n", content)
    else:
        print("ERR:", res.text)

if __name__ == "__main__":
    analyze_video_visually(Path("media/viral_sources/sOZrJUkCLYU.mp4"))
