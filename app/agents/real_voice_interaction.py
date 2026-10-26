"""JARVIS interaction primitives adapted for VyralX (stdlib, no fake ASR).

Adaptive energy gating, speech endpointing, echo rejection, clap detection and
One-Euro motion smoothing. Words must come from a real transcriber/browser.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Callable


@dataclass(frozen=True)
class VoiceEvent:
    kind: str
    at: float
    energy: float
    threshold: float


class AdaptiveVoiceGate:
    def __init__(self, floor: float = 0.01, start_seconds: float = 0.11,
                 silence_seconds: float = 0.65, max_seconds: float = 20) -> None:
        if floor<=0 or start_seconds<0 or silence_seconds<=0 or max_seconds<=silence_seconds:
            raise ValueError('invalid voice gate settings')
        self.floor, self.start_seconds, self.silence_seconds, self.max_seconds = floor,start_seconds,silence_seconds,max_seconds
        self.armed: float | None = None
        self.started: float | None = None
        self.last_loud = 0.0
        self.last_at = -math.inf

    def feed(self, samples: list[float], at: float, playback: bool = False) -> VoiceEvent:
        if not samples or not math.isfinite(at) or at<self.last_at or any(not math.isfinite(s) or abs(s)>1 for s in samples):
            raise ValueError('ordered finite normalized PCM frames required')
        self.last_at = at
        energy = math.sqrt(sum(s*s for s in samples)/len(samples))
        threshold = max(0.008,self.floor*2.6)*(2.4 if playback else 1)
        kind = 'quiet'
        if self.started is None:
            if energy>=threshold:
                self.armed = at if self.armed is None else self.armed
                if at-self.armed>=self.start_seconds:
                    self.started, self.last_loud = self.armed, at
                    kind = 'speech_start'
            else:
                self.armed = None
                self.floor = max(0.002,self.floor+(energy-self.floor)*(0.0008 if energy>self.floor else 0.02))
        else:
            kind = 'speech'
            if energy>=threshold*0.6:
                self.last_loud = at
            if at-self.last_loud>=self.silence_seconds or at-self.started>=self.max_seconds:
                self.started = self.armed = None
                kind = 'speech_end'
        return VoiceEvent(kind,at,energy,threshold)


class UtteranceAssembler:
    """Wake/debounce, incomplete-turn delay and assistant-echo rejection."""

    CONTINUES = re.compile(r'\b(and|or|but|because|to|of|in|on|at|for|with|from|the|a|my|your|is|are|can|could|would|will)$',re.I)
    WAKE = re.compile(r'\b(?:(?:hey|hi|okay|ok)\s+)?(?:jarvis|friday|jervis|jarvys)\b(?![\w\x27])[,\s:;.!?-]*',re.I)

    def __init__(self, wake_required: bool = True) -> None:
        self.wake_required = wake_required
        self.awake_until = 0.0
        self.last_wake = -math.inf
        self.buffer = ''
        self.updated = 0.0
        self.spoken = ''
        self.spoken_at = -math.inf

    def speaking(self, text: str, at: float) -> None:
        self.spoken, self.spoken_at = text.lower(),at

    def add(self, text: str, at: float) -> dict:
        text = ' '.join(text.split())
        if not text:
            return {'status':'empty','text':''}
        wake = self.WAKE.search(text)
        if self.spoken and at-self.spoken_at<30 and not wake:
            words = set(re.findall(r'\w+',text.lower()))
            echo = set(re.findall(r'\w+',self.spoken))
            if words and len(words & echo)/len(words)>0.85:
                return {'status':'echo','text':''}
        if wake:
            if at-self.last_wake<1.5 and not text[wake.end():].strip():
                return {'status':'debounced','text':''}
            self.last_wake, self.awake_until = at, at+30
            text = text[wake.end():].strip()
        elif self.wake_required and at>self.awake_until:
            return {'status':'asleep','text':''}
        if not text:
            return {'status':'awake','text':''}
        self.buffer = (self.buffer+' '+text).strip()
        self.updated = at
        return {'status':'buffering','text':self.buffer}

    def flush(self, at: float, force: bool = False) -> str | None:
        if not self.buffer:
            return None
        incomplete = bool(self.CONTINUES.search(self.buffer) or re.search(r'[,;:–—-]$',self.buffer))
        delay = 1.5 if incomplete else 0.25
        if not force and at-self.updated<delay:
            return None
        result,self.buffer = self.buffer,''
        return result


class OneEuroFilter:
    def __init__(self, min_cutoff: float = 1, beta: float = 0, derivative_cutoff: float = 1) -> None:
        if min_cutoff<=0 or beta<0 or derivative_cutoff<=0:
            raise ValueError('invalid filter parameters')
        self.min_cutoff,self.beta,self.derivative_cutoff = min_cutoff,beta,derivative_cutoff
        self.value: float | None = None
        self.velocity = 0.0
        self.at: float | None = None

    @staticmethod
    def alpha(cutoff: float, dt: float) -> float:
        return 1/(1+1/(2*math.pi*cutoff*dt))

    def filter(self, value: float, at: float) -> float:
        if not math.isfinite(value) or not math.isfinite(at) or (self.at is not None and at<self.at):
            raise ValueError('finite ordered samples required')
        if self.value is None:
            self.value,self.at = value,at
            return value
        dt = min(0.2,max(1/240,at-self.at))
        derivative = (value-self.value)/dt
        alpha = self.alpha(self.derivative_cutoff,dt)
        self.velocity += alpha*(derivative-self.velocity)
        alpha = self.alpha(self.min_cutoff+self.beta*abs(self.velocity),dt)
        self.value += alpha*(value-self.value)
        self.at = at
        return self.value

    def reset(self) -> None:
        self.value,self.at,self.velocity = None,None,0


class ClapDetector:
    def __init__(self) -> None:
        self.floor = 0.01
        self.history: list[float] = []
        self.candidate: tuple[float,float] | None = None
        self.last_clap = -math.inf
        self.last_at = -math.inf

    def feed(self, energy: float, at: float) -> bool:
        if not 0<=energy<=1 or not math.isfinite(at) or at<self.last_at:
            raise ValueError('invalid energy/time')
        self.last_at = at
        quiet = len(self.history)>=5 and max(self.history[-5:])<max(0.02,self.floor*2)
        self.history = (self.history+[energy])[-20:]
        if self.candidate:
            began,peak = self.candidate
            if energy<peak*0.35 and at-began<=0.13:
                self.candidate = None
                self.last_clap = at
                return True
            if at-began>0.26:
                self.candidate = None
        elif at-self.last_clap>=1.2 and quiet and energy>=max(0.055,self.floor*7):
            self.candidate = (at,energy)
        elif energy<self.floor*3:
            self.floor = max(0.002,self.floor+(energy-self.floor)*0.05)
        return False


class VoiceInteractionEngine:
    def __init__(self, respond: Callable[[str],dict], wake_required: bool = True) -> None:
        self.respond = respond
        self.gate = AdaptiveVoiceGate()
        self.assembler = UtteranceAssembler(wake_required)
        self.clap = ClapDetector()
        self.motion = [OneEuroFilter(beta=0.4),OneEuroFilter(beta=0.4)]

    def transcript(self, text: str, at: float, force: bool = True) -> dict:
        received = self.assembler.add(text,at)
        utterance = self.assembler.flush(at,force) if received['status']=='buffering' else None
        if not utterance:
            return received
        reply = self.respond(utterance)
        self.assembler.speaking(reply.get('text',''),at)
        return {'status':'answered','utterance':utterance,'reply':reply}

    def motion_frame(self, x: float, y: float, at: float) -> dict:
        """Smooth supplied normalized landmarks; this does not invent camera detections."""
        if not 0<=x<=1 or not 0<=y<=1:
            raise ValueError('normalized landmark coordinates required')
        return {'x':self.motion[0].filter(x,at),'y':self.motion[1].filter(y,at),'at':at}

    def frame(self, samples: list[float], at: float, playback: bool = False) -> dict:
        from dataclasses import asdict
        event = self.gate.feed(samples,at,playback)
        clap = self.clap.feed(event.energy,at)
        if clap:
            self.assembler.awake_until = at+30
        return {**asdict(event),'clap':clap,'barge_in':playback and event.kind=='speech_start'}
