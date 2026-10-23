import asyncio
from typing import Any
import edge_tts

async def get_word_cues(script: str, voice: str) -> tuple[bytes, list[dict[str, Any]]]:
    comm = edge_tts.Communicate(script, voice, boundary="WordBoundary")
    audio_bytes = b""
    words = []
    
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            audio_bytes += chunk["data"]
        elif chunk["type"] == "WordBoundary":
            st = chunk["offset"] / 1e7
            dur = chunk["duration"] / 1e7
            words.append({"text": chunk["text"], "start": st, "end": st + dur})
            
    # Group words into 2-word chunks
    chunks = []
    i = 0
    while i < len(words):
        # If last remaining word is alone, can pair with previous or stand alone
        if i + 1 < len(words):
            pair = words[i:i+2]
            chunks.append({
                "text": f"{pair[0]['text']} {pair[1]['text']}",
                "start": pair[0]["start"],
                "end": pair[1]["end"]
            })
            i += 2
        else:
            single = words[i]
            chunks.append({
                "text": single["text"],
                "start": single["start"],
                "end": single["end"]
            })
            i += 1
            
    # Bridge small gaps (< 0.35s) so subtitles don't flicker between consecutive chunks
    for j in range(len(chunks) - 1):
        gap = chunks[j+1]["start"] - chunks[j]["end"]
        if 0 < gap <= 0.35:
            chunks[j]["end"] = chunks[j+1]["start"]
            
    return audio_bytes, chunks

async def main():
    script = "He dressed up in a luxury tuxedo for a five-star Michelin dinner, but the menu had other plans."
    audio, cues = await get_word_cues(script, "en-US-GuyNeural")
    print(f"Generated {len(cues)} cues, audio size: {len(audio)} bytes")
    for c in cues:
        print(f"[{c['start']:05.2f}s -> {c['end']:05.2f}s] {c['text']}")

if __name__ == "__main__":
    asyncio.run(main())
