import asyncio
import edge_tts

async def test():
    comm = edge_tts.Communicate("He dressed up in a luxury tuxedo for a five-star Michelin dinner", "en-US-GuyNeural", boundary="WordBoundary")
    words = []
    async for chunk in comm.stream():
        if chunk["type"] == "WordBoundary":
            st = chunk["offset"] / 1e7
            dur = chunk["duration"] / 1e7
            words.append((chunk["text"], st, st + dur))
    for w, s, e in words:
        print(f"{w:12s} | {s:.2f}s -> {e:.2f}s (dur: {e-s:.2f}s)")

if __name__ == "__main__":
    asyncio.run(test())
