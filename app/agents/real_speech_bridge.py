"""Server-held ElevenLabs STT/TTS adapters with browser fallback capability flags."""
from __future__ import annotations

import json
import re
import secrets
from typing import Callable
from urllib.request import Request, urlopen


class SpeechBridge:
    def __init__(self, key: str = '', voice_id: str = '', transport: Callable = urlopen) -> None:
        self.key,self.voice_id,self.transport = key,voice_id,transport

    def capabilities(self) -> dict:
        return {'stt':bool(self.key),'tts':bool(self.key and self.voice_id),
                'fallback':'browser_speech','secrets_in_browser':False}

    def transcribe(self, audio: bytes, media_type: str = 'audio/webm') -> str:
        if not self.key:
            raise RuntimeError('Server speech recognition is not configured; use browser recognition')
        if not audio or len(audio)>4*1024*1024 or media_type not in {'audio/webm','audio/ogg','audio/wav','audio/mp4'}:
            raise ValueError('unsupported or oversized audio')
        boundary = 'friday'+secrets.token_hex(16)
        ext = {'audio/webm':'webm','audio/ogg':'ogg','audio/wav':'wav','audio/mp4':'mp4'}[media_type]
        data = (f'--{boundary}\r\nContent-Disposition: form-data; name="model_id"\r\n\r\nscribe_v1\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="speech.{ext}"\r\n'
                f'Content-Type: {media_type}\r\n\r\n').encode()+audio+f'\r\n--{boundary}--\r\n'.encode()
        request = Request('https://api.elevenlabs.io/v1/speech-to-text',data=data,
            headers={'xi-api-key':self.key,'Content-Type':'multipart/form-data; boundary='+boundary},method='POST')
        with self.transport(request,timeout=30) as response:
            raw = response.read(1024*1024+1)
            if len(raw)>1024*1024:
                raise ValueError('transcription response too large')
            text = json.loads(raw).get('text')
            if not isinstance(text,str):
                raise ValueError('provider returned no transcript')
            return text

    def synthesize(self, text: str) -> bytes:
        if not self.key or not self.voice_id:
            raise RuntimeError('Server voice is not configured; use browser speech synthesis')
        if not text.strip() or len(text)>4000 or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',self.voice_id):
            raise ValueError('invalid speech text or configured voice')
        request = Request('https://api.elevenlabs.io/v1/text-to-speech/'+self.voice_id,
            data=json.dumps({'text':text,'model_id':'eleven_multilingual_v2'}).encode(),
            headers={'xi-api-key':self.key,'Content-Type':'application/json','Accept':'audio/mpeg'},method='POST')
        with self.transport(request,timeout=30) as response:
            audio = response.read(8*1024*1024+1)
            if len(audio)>8*1024*1024:
                raise ValueError('speech response too large')
            return audio
