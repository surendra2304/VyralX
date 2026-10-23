import asyncio
import edge_tts
from pathlib import Path

def sec_to_ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"

async def get_cues(script: str, voice: str):
    comm = edge_tts.Communicate(script, voice)
    cues = []
    audio_data = b""
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            audio_data += chunk["data"]
        elif chunk["type"] == "SentenceBoundary":
            start = chunk["offset"] / 1e7
            dur = chunk["duration"] / 1e7
            sentence = chunk["text"].strip()
            words = sentence.split()
            # chunk into groups of 3-4 words max
            chunk_size = 3
            chunks = [" ".join(words[i:i+chunk_size]) for i in range(0, len(words), chunk_size)]
            total_chars = sum(len(c) for c in chunks)
            curr_start = start
            for c in chunks:
                chunk_dur = dur * (len(c) / total_chars)
                cues.append({"start": curr_start, "end": curr_start + chunk_dur, "text": c})
                curr_start += chunk_dur
    return audio_data, cues

def generate_ass(cues: list, output_path: Path):
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: ViralShorts,Segoe UI,44,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,3.5,1.5,2,80,80,380,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for c in cues:
        st = sec_to_ass_time(c["start"])
        et = sec_to_ass_time(c["end"])
        txt = c["text"]
        # Accent numbers or key capitalized words with gold highlight
        # e.g., if contains numbers or dollar sign:
        if any(char.isdigit() for char in txt) or "$" in txt:
            txt = f"{{\\c&H0000FFFF&}}{txt}{{\\c&H00FFFFFF&}}"
        events.append(f"Dialogue: 0,{st},{et},ViralShorts,,0,0,0,,{txt}")

    output_path.write_text(header + "\n".join(events), encoding="utf-8")
    print(f"Generated ASS with {len(events)} cues at {output_path}")

async def main():
    script = (
        "When this customer jokingly asked for a discount, the salesman hit him with the ultimate counter-offer: "
        "nine million, nine hundred ninety-nine thousand dollars. "
        "The stone-cold deadpan delivery turned an everyday interaction into one of the most viral negotiation memes on the internet."
    )
    voice = "en-US-GuyNeural"
    audio_data, cues = await get_cues(script, voice)
    Path("test_audio.mp3").write_bytes(audio_data)
    generate_ass(cues, Path("test_guy.ass"))
    for c in cues[:5]:
        print(f"{c['start']:.2f}s - {c['end']:.2f}s: {c['text']}")

if __name__ == "__main__":
    asyncio.run(main())
