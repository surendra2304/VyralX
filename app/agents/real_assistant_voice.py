"""Real WAV -> transcription -> FRIDAY response -> native TTS, with explicit adapters."""
from __future__ import annotations

from dataclasses import dataclass
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
from typing import Callable
from urllib.request import Request, urlopen
import uuid
import wave


@dataclass(frozen=True)
class VoiceTurn:
    transcript: str
    response: dict
    audio: bytes
    speech_status: str


class ElevenLabsSpeechSynthesizer:
    """Optional, explicit ElevenLabs PCM-to-WAV adapter for the Drive voice guide."""

    def __init__(self, api_key: str, voice_id: str, opener: Callable = urlopen,
                 timeout: float = 20) -> None:
        if not api_key.strip() or not voice_id.strip() or len(voice_id)>128 or not 0 < timeout <= 60:
            raise ValueError("ElevenLabs key, voice ID and bounded timeout required")
        self.api_key=api_key.strip()
        self.voice_id=voice_id.strip()
        self.opener=opener
        self.timeout=timeout

    def __call__(self, text: str) -> bytes:
        import json
        from urllib.error import HTTPError
        from urllib.parse import quote
        if not isinstance(text,str) or not text.strip() or len(text)>5000:
            raise ValueError("ElevenLabs text must contain 1-5000 characters")
        url=("https://api.elevenlabs.io/v1/text-to-speech/"+quote(self.voice_id,safe="")+
             "?output_format=pcm_16000")
        request=Request(url,data=json.dumps({"text":text,"model_id":"eleven_multilingual_v2"}).encode(),
            headers={"xi-api-key":self.api_key,"Content-Type":"application/json",
                     "Accept":"application/octet-stream"},method="POST")
        try:
            with self.opener(request,timeout=self.timeout) as response:
                raw=response.read(20*1024*1024+1)
        except HTTPError as error:
            status=error.code
            error.close()
            raise RuntimeError(f"ElevenLabs speech provider HTTP {status}") from None
        if not raw or len(raw)>20*1024*1024 or len(raw)%2:
            raise ValueError("invalid or oversized ElevenLabs PCM response")
        output=io.BytesIO()
        with wave.open(output,"wb") as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(raw)
        return output.getvalue()


class AssistantVoiceEngine:
    def __init__(self, assistant: Callable[[str], dict], recognizer: Callable | None = None,
                 synthesizer: Callable | None = None, opener: Callable = urlopen,
                 runner: Callable = subprocess.run) -> None:
        self.assistant, self.recognizer = assistant, recognizer
        self.synthesizer, self.opener, self.runner = synthesizer, opener, runner

    @staticmethod
    def inspect_wav(audio: bytes) -> dict:
        if len(audio) > 10*1024*1024:
            raise ValueError("WAV exceeds 10 MiB")
        try:
            with wave.open(io.BytesIO(audio)) as wav:
                channels, width, rate, frames = wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes()
                if channels != 1 or width != 2 or not 8000 <= rate <= 48000 or not 0 < frames/rate <= 60:
                    raise ValueError("expected mono 16-bit PCM WAV, 8-48 kHz, up to 60 seconds")
                raw = wav.readframes(frames)
                if len(raw) != frames*2:
                    raise ValueError("truncated WAV")
        except (wave.Error, EOFError) as error:
            raise ValueError("invalid WAV") from error
        samples = struct.unpack(f"<{frames}h", raw)
        rms = math.sqrt(sum(x*x for x in samples)/frames)/32768
        return {"duration": frames/rate, "sample_rate": rate, "rms": rms}

    def transcribe(self, audio: bytes) -> str:
        self.inspect_wav(audio)
        if self.recognizer:
            text = self.recognizer(audio)
        else:
            key = os.environ.get("GROQ_API_KEY", "").strip()
            if not key:
                raise RuntimeError("speech recognizer not configured; use the text endpoint or provide a recognizer")
            boundary = uuid.uuid4().hex
            body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\nwhisper-large-v3-turbo\r\n"
                    f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"speech.wav\"\r\n"
                    "Content-Type: audio/wav\r\n\r\n").encode() + audio + f"\r\n--{boundary}--\r\n".encode()
            request = Request("https://api.groq.com/openai/v1/audio/transcriptions", data=body,
                headers={"Authorization": f"Bearer {key}", "Content-Type": f"multipart/form-data; boundary={boundary}"})
            with self.opener(request, timeout=30) as response:
                raw = response.read(1024*1024+1)
            if len(raw) > 1024*1024:
                raise ValueError("transcription response too large")
            text = json.loads(raw).get("text", "")
        if not isinstance(text, str) or not text.strip() or len(text) > 10000:
            raise ValueError("empty or invalid transcript")
        return text.strip()

    def synthesize(self, text: str, allow_cloud_synthesis: bool = False) -> bytes:
        if not text.strip() or len(text) > 10000:
            raise ValueError("invalid speech text")
        if self.synthesizer:
            result = self.synthesizer(text)
        else:
            api_key=os.environ.get("ELEVENLABS_API_KEY","").strip()
            voice_id=os.environ.get("ELEVENLABS_VOICE_ID","").strip()
            if api_key and voice_id and allow_cloud_synthesis:
                result=ElevenLabsSpeechSynthesizer(api_key,voice_id,opener=self.opener)(text)
                if not result.startswith(b"RIFF"):
                    raise ValueError("ElevenLabs did not return a WAV container")
                return result
            executable = shutil.which("espeak-ng") or shutil.which("espeak")
            if not executable:
                raise RuntimeError("native WAV TTS requires espeak-ng or an injected synthesizer")
            result = self.runner([executable, "--stdout", "--stdin"], input=text.encode(),
                                 capture_output=True, timeout=30, shell=False)
            if result.returncode:
                raise RuntimeError("native TTS failed")
            result = result.stdout
        if not isinstance(result, bytes) or not result.startswith(b"RIFF"):
            raise ValueError("synthesizer did not return WAV")
        return result

    def turn(self, audio: bytes, speak: bool = True,
             allow_cloud_synthesis: bool = False) -> VoiceTurn:
        metrics = self.inspect_wav(audio)
        if metrics["rms"] < 0.001:
            return VoiceTurn("", {"text": "No audible speech detected.", "source": "voice"}, b"", "silence")
        transcript = self.transcribe(audio)
        command = re.sub(r"\bjarvis\b", " ", transcript, flags=re.I)
        command = " ".join(command.split(" ")).strip(" ,.!?\t\r\n")
        wake_only = command.casefold() in {"hey", "hello", "hi"}
        response = (self.assistant(command) if command and not wake_only else
                    {"text": "Yes, I'm listening.", "source": "local", "agent": "FRIDAY"})
        if not isinstance(response, dict) or not isinstance(response.get("text"), str):
            response = {"text": "FRIDAY could not produce a text response.", "source": "fallback", "agent": "FRIDAY"}
        if not speak:
            return VoiceTurn(transcript, response, b"", "disabled")
        try:
            synthesized = self.synthesize(response["text"], allow_cloud_synthesis=allow_cloud_synthesis)
            return VoiceTurn(transcript, response, synthesized, "synthesized")
        except (RuntimeError, OSError, subprocess.TimeoutExpired):
            return VoiceTurn(transcript, response, b"", "text_only")

    def listen(self, recorder: Callable[[], bytes | None], output: Callable[[VoiceTurn], None],
               max_turns: int = 100, allow_cloud_synthesis: bool = False) -> int:
        """Bounded live loop; recorders own hardware permission and cancellation."""
        if not 1 <= max_turns <= 1000:
            raise ValueError("invalid voice loop budget")
        completed = 0
        for _ in range(max_turns):
            audio = recorder()
            if audio is None:
                break
            output(self.turn(audio, allow_cloud_synthesis=allow_cloud_synthesis))
            completed += 1
        return completed


class NativeMicrophone:
    """Linux ALSA capture. Construct explicitly on the user's host, never via HTTP."""

    def __init__(self, seconds: int = 8, runner: Callable = subprocess.run) -> None:
        if not 1 <= seconds <= 30:
            raise ValueError("capture must be between 1 and 30 seconds")
        self.seconds, self.runner = seconds, runner

    def __call__(self) -> bytes:
        executable = shutil.which("arecord")
        if not executable:
            raise RuntimeError("native recording requires ALSA arecord or an injected recorder")
        result = self.runner([executable, "-q", "-t", "wav", "-f", "S16_LE", "-c", "1", "-r", "16000",
                              "-d", str(self.seconds), "-"], capture_output=True, timeout=self.seconds+5, shell=False)
        if result.returncode:
            raise RuntimeError("microphone recording failed")
        return result.stdout


class SpeechRecognitionRecorder:
    """Optional PyAudio/SpeechRecognition mic adapter; no audio is sent here."""

    def __init__(self, energy_threshold: int | None = None, pause_threshold: float = 0.8,
                 phrase_seconds: int = 8) -> None:
        if not 0.2 <= pause_threshold <= 3 or not 1 <= phrase_seconds <= 30:
            raise ValueError("invalid speech-recognition bounds")
        try:
            import speech_recognition as sr
        except ImportError as error:
            raise RuntimeError("voice capture requires SpeechRecognition and a microphone backend") from error
        self._sr = sr
        self.recognizer = sr.Recognizer()
        self.recognizer.dynamic_energy_threshold = energy_threshold is None
        if energy_threshold is not None:
            if energy_threshold < 1: raise ValueError("energy threshold must be positive")
            self.recognizer.energy_threshold = energy_threshold
        self.recognizer.pause_threshold = pause_threshold
        try:
            self.microphone = sr.Microphone()
        except (OSError, AttributeError) as error:
            raise RuntimeError("microphone unavailable; grant OS microphone permission or use text API") from error
        with self.microphone as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
        self.phrase_seconds = phrase_seconds

    def __call__(self) -> bytes:
        with self.microphone as source:
            audio = self.recognizer.listen(source, timeout=None, phrase_time_limit=self.phrase_seconds)
        return audio.get_wav_data(convert_rate=16000, convert_width=2)


class NativeSpeechOutput:
    """Native system voice output through argument-vector process calls only."""

    def __init__(self, runner: Callable = subprocess.run) -> None:
        self.runner = runner

    def __call__(self, text: str) -> str:
        if not text:
            return "empty"
        executable = (shutil.which("say") if sys.platform == "darwin" else
                      shutil.which("espeak-ng") or shutil.which("espeak") if sys.platform.startswith("linux") else None)
        if executable:
            args=([executable,"-f","-"] if sys.platform=="darwin" else [executable,"--stdin"])
            result=self.runner(args,input=text.encode("utf-8"),capture_output=True,timeout=30,shell=False)
            return "spoken" if result.returncode==0 else "failed"
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.say(text)
            engine.runAndWait()
            return "spoken"
        except Exception:
            return "unavailable"


def main() -> int:
    """Run a true live voice loop on a host with an explicitly consented provider."""
    import argparse
    import getpass
    import os
    parser = argparse.ArgumentParser(description="FRIDAY/Jarvis local microphone assistant")
    parser.add_argument("--allow-cloud", action="store_true", help="send captured audio to Groq Whisper and unknown queries to the configured Groq chat provider")
    parser.add_argument("--text-only", action="store_true", help="disable synthesized speech output")
    args = parser.parse_args()
    if not args.allow_cloud:
        parser.error("microphone audio requires explicit --allow-cloud consent (or use the text API)")
    if not os.environ.get("GROQ_API_KEY", "").strip():
        parser.error("GROQ_API_KEY is required for cloud speech recognition")
    from friday_core.real_cross_agent_engine import CrossAgentEngine
    engine = CrossAgentEngine()
    recorder = SpeechRecognitionRecorder()
    voice = engine.voice_engine()
    speaker = NativeSpeechOutput()
    print("Captured speech is sent to Groq Whisper. Unknown text may go to Groq chat.")
    if os.environ.get("ELEVENLABS_API_KEY") and os.environ.get("ELEVENLABS_VOICE_ID"):
        print("Response speech may also be sent to ElevenLabs because --allow-cloud was selected.")
    print("Local desktop actions require a separate approval prompt. Press Ctrl-C to stop.")
    def output(turn: VoiceTurn) -> None:
        print(f"You: {turn.transcript}\nFRIDAY: {turn.response.get('text', '')}")
        action = turn.response.get("action")
        if action:
            preview = action.get("target", "")
            approval = input(f"Approve this local action ({preview})? Type YES: ").strip()
            if approval == "YES":
                result = engine.local_action_engine().execute(action["action_id"], approved=True)
                print(f"Action: {result['status']}")
            else:
                engine.local_action_engine().execute(action["action_id"], approved=False)
                print("Action not executed.")
        if not args.text_only:
            print("Speech:", speaker(turn.response.get("text", "")))
    try:
        voice.listen(recorder, output, max_turns=1000, allow_cloud_synthesis=True)
    except KeyboardInterrupt:
        print("\nVoice assistant stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
