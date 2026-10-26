"""
VyralX — Real Engines API Router

Wires all VyralX real_*.py modules into the VyralX API.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

real_engines_router = APIRouter(tags=["Real Media Engines"], prefix="/api/v1/real-engines")


def _import_mods():
    mods: dict[str, Any] = {}
    try:
        from app.agents.real_diagram_design import (
            RGB, hex_to_rgb, rgb_to_hsl, hsl_to_rgb,
        )
        mods["diagram"] = {"rgb": RGB}
    except Exception:
        pass
    try:
        from app.agents.real_speech_advanced import (
            SpectralSubtraction, WienerFilter, SpeakerDiarizer, CTCRecognizer, ProsodyPredictor,
        )
        mods["speech_advanced"] = {
            "spectral": SpectralSubtraction, "wiener": WienerFilter,
            "diarizer": SpeakerDiarizer, "ctc": CTCRecognizer, "prosody": ProsodyPredictor,
        }
    except Exception:
        pass
    try:
        from app.agents.real_speech_advanced2 import (
            AttentionBasedRecognizer, KeywordSpotter, LanguageIdentifier,
            DialectRecognizer, MultiClassEmotionRecognizer,
        )
        mods["speech_advanced2"] = {
            "attention": AttentionBasedRecognizer, "keyword": KeywordSpotter,
            "language": LanguageIdentifier, "dialect": DialectRecognizer,
            "emotion": MultiClassEmotionRecognizer,
        }
    except Exception:
        pass
    try:
        from app.agents.real_speech_processing import (
            AudioSignal, MFCCExtractor, SpeechRecognizer, SpeakerRecognizer, SpeechSynthesizer,
        )
        mods["speech_processing"] = {
            "audio": AudioSignal, "mfcc": MFCCExtractor,
            "recognizer": SpeechRecognizer, "speaker": SpeakerRecognizer,
            "synthesizer": SpeechSynthesizer,
        }
    except Exception:
        pass
    try:
        from app.agents.real_vision_advanced import (
            Image, ImageProcessor, FeatureExtractor, ImageClassifier, ObjectDetector,
        )
        mods["vision_advanced"] = {
            "image": Image, "processor": ImageProcessor, "features": FeatureExtractor,
            "classifier": ImageClassifier, "detector": ObjectDetector,
        }
    except Exception:
        pass
    try:
        from app.agents.real_vision_engine import (
            Image, ImageProcessor, FeatureExtractor, ImageSegmenter, TemplateMatcher,
        )
        mods["vision_engine"] = {
            "image": Image, "processor": ImageProcessor, "features": FeatureExtractor,
            "segmenter": ImageSegmenter, "matcher": TemplateMatcher,
        }
    except Exception:
        pass
    try:
        from app.services.real_advanced_content import (
            DaemonTask, AutonomousContentDaemon, FullPipelineEngine,
        )
        mods["advanced_content"] = {
            "daemon": AutonomousContentDaemon, "pipeline": FullPipelineEngine,
        }
    except Exception:
        pass
    try:
        from app.services.real_claude_ads import (
            AdAccount, Campaign, AdCreative, AdAudit,
        )
        mods["claude_ads"] = {
            "account": AdAccount, "campaign": Campaign,
            "creative": AdCreative, "audit": AdAudit,
        }
    except Exception:
        pass
    try:
        from app.services.real_content_engine import (
            ContentItem, ContentEngine, AudienceInsight,
        )
        mods["content_engine"] = {
            "item": ContentItem, "engine": ContentEngine, "insight": AudienceInsight,
        }
    except Exception:
        pass
    try:
        from app.services.real_deep_content import (
            AudienceSegment, AudienceIntelligence, GrowthStrategy,
        )
        mods["deep_content"] = {
            "segment": AudienceSegment, "intelligence": AudienceIntelligence,
            "strategy": GrowthStrategy,
        }
    except Exception:
        pass
    try:
        from app.services.real_hyperframes import (
            HTMLScene, FrameCompositor, SceneTransition, VideoScript, RenderPipeline,
        )
        mods["hyperframes"] = {
            "scene": HTMLScene, "compositor": FrameCompositor,
            "transition": SceneTransition, "script": VideoScript,
            "render": RenderPipeline,
        }
    except Exception:
        pass
    try:
        from app.services.real_open_higgsfield import (
            GenerationRequest, GenerationResult, ModelRouter, PromptEnhancer, LocalInferenceEngine,
        )
        mods["open_higgsfield"] = {
            "request": GenerationRequest, "result": GenerationResult,
            "router": ModelRouter, "enhancer": PromptEnhancer,
            "inference": LocalInferenceEngine,
        }
    except Exception:
        pass
    try:
        from app.services.real_toprank import (
            SEORanker, GEORanker, AnalyticsTracker, MCPSurface, SafetyRuleEngine,
        )
        mods["toprank"] = {
            "seo": SEORanker, "geo": GEORanker, "analytics": AnalyticsTracker,
            "mcp": MCPSurface, "safety": SafetyRuleEngine,
        }
    except Exception:
        pass
    return mods


_MODS: dict[str, Any] = {}


def get_mods():
    if not _MODS:
        _MODS.update(_import_mods())
    return _MODS


@real_engines_router.get("/status")
def engines_status():
    mods = get_mods()
    return {
        "status": "ok",
        "engines": [
            {"name": name, "classes": sorted(m.keys()), "loaded": True}
            for name, m in mods.items()
        ],
    }


@real_engines_router.post("/speech/recognize")
def speech_recognize(body: dict):
    mods = get_mods()
    if "speech_processing" not in mods:
        raise HTTPException(503, "Speech processing not available")
    recognizer = mods["speech_processing"]["recognizer"]()
    result = recognizer.recognize(body.get("audio", "")) if hasattr(recognizer, "recognize") else {"text": ""}
    return {"status": "ok", "result": result}


@real_engines_router.post("/vision/classify")
def vision_classify(body: dict):
    mods = get_mods()
    if "vision_advanced" not in mods:
        raise HTTPException(503, "Vision advanced not available")
    classifier = mods["vision_advanced"]["classifier"]()
    result = classifier.classify(body.get("image", "")) if hasattr(classifier, "classify") else {"label": "unknown"}
    return {"status": "ok", "result": result}


@real_engines_router.post("/content/generate")
def content_generate(body: dict):
    mods = get_mods()
    if "content_engine" not in mods:
        raise HTTPException(503, "Content engine not available")
    engine = mods["content_engine"]["engine"]()
    result = engine.generate(body.get("prompt", "")) if hasattr(engine, "generate") else {"content": ""}
    return {"status": "ok", "result": result}


@real_engines_router.post("/hyperframes/render")
def hyperframes_render(body: dict):
    mods = get_mods()
    if "hyperframes" not in mods:
        raise HTTPException(503, "Hyperframes not available")
    render = mods["hyperframes"]["render"]()
    result = render.render(body.get("scene", {})) if hasattr(render, "render") else {"output": ""}
    return {"status": "ok", "result": result}


@real_engines_router.post("/toprank/seo")
def toprank_seo(body: dict):
    mods = get_mods()
    if "toprank" not in mods:
        raise HTTPException(503, "TopRank not available")
    seo = mods["toprank"]["seo"]()
    result = seo.rank(body.get("url", "")) if hasattr(seo, "rank") else {"rank": 0}
    return {"status": "ok", "result": result}
