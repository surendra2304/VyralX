import asyncio
import edge_tts

async def main():
    text = (
        "This might sound like a sports car engine. "
        "But it is actually an 8-month-old cheetah cub purring. "
        "Unlike lions and tigers, cheetahs cannot roar. "
        "Instead, they purr at a steady frequency whenever they feel calm and content."
    )
    comm = edge_tts.Communicate(text, "en-US-ChristopherNeural")
    audio = b""
    cues = []
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            audio += chunk["data"]
        elif chunk["type"] == "SentenceBoundary":
            s = chunk["offset"] / 10_000_000.0
            d = chunk["duration"] / 10_000_000.0
            cues.append({
                "start": round(s, 2),
                "end": round(s + d, 2),
                "text": chunk["text"],
            })

    print(f"Synthesized {len(audio)} bytes of audio ({round(cues[-1]['end'] if cues else 0, 1)} seconds)")
    for c in cues:
        print(f"  [{c['start']:.2f}s - {c['end']:.2f}s]: {c['text']}")

if __name__ == "__main__":
    asyncio.run(main())
