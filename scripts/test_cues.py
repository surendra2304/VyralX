import asyncio
import edge_tts

VIDEOS_CONFIG = {
    'A_Q2qpbHrqo': (
        'He dressed up in a luxury tuxedo for a five-star Michelin dinner, but the menu had other plans. '
        'Instead of gourmet food, the waitress serves him a plate of literal soap bubbles. '
        'And just when he thinks it cannot get any more ridiculous, she brings out a toy bubble gun and blasts his head with foam. '
        'The final bill for this soap dinner? Exactly nine million, nine hundred ninety-nine thousand dollars.'
    ),
    'hx265ujsLVU': (
        'When your friends try to roast you in the hallway, but you have maximum main character energy. '
        'While the rest of the squad is laughing and joking around, she delivers the cleanest eye-roll on the internet '
        'and struts away without breaking character for a single second. That is how you own the room.'
    )
}

async def check():
    for vid, script in VIDEOS_CONFIG.items():
        comm = edge_tts.Communicate(script, 'en-US-GuyNeural')
        cues = []
        async for chunk in comm.stream():
            if chunk['type'] == 'SentenceBoundary':
                words = chunk['text'].strip().split()
                chunk_size = 2
                chunks = [' '.join(words[i:i+chunk_size]) for i in range(0, len(words), chunk_size)]
                for ch in chunks:
                    cues.append(ch)
        print(f'=== {vid} ({len(cues)} cues) ===')
        max_c = max(cues, key=len)
        print(f'Longest cue: "{max_c}" ({len(max_c)} chars)')
        for c in cues:
            print(f'  "{c}"')

if __name__ == '__main__':
    asyncio.run(check())
