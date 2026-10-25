"""
VyralX — Open-Higgsfield-AI Engine

Unrestricted open-source AI video/image generation studio with 600+ models
(Flux, Midjourney, Kling, Sora, Veo). Self-hosted generative pipeline,
multi-model routing, and local inference concepts.

Tests: tests/test_real_batch4a.py
"""

from __future__ import annotations

import hashlib
import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


MODEL_CATALOG = [
    "Flux.1-dev", "Flux.1-schnell", "Flux.1-Pro",
    "Midjourney-v6", "Midjourney-v6.1", "Midjourney-niji-6",
    "Kling-1.6", "Kling-2.1", "Kling-2.5",
    "Sora-OpenAI", "Sora-2", "Veo-3",
    "SDXL", "SDXL-Turbo", "SD-3.5",
    "Stable-Video-Diffusion", "AnimateDiff", "CogVideoX",
    "LTX-Video", "Mochi-1", "HunyuanVideo",
    "Ideogram-v2", "Playground-v2.5", "PixArt-alpha",
]


@dataclass
class GenerationRequest:
    """A generation request for a generative model."""
    request_id: str
    model: str
    prompt: str
    negative_prompt: str = ""
    width: int = 1024
    height: int = 1024
    num_steps: int = 20
    guidance_scale: float = 7.0
    seed: int = 42
    batch_size: int = 1
    output_format: str = "png"

    @staticmethod
    def create_id(prompt: str) -> str:
        return f"gen-{hashlib.md5(prompt.encode()).hexdigest()[:12]}"

    @property
    def resolution(self) -> str:
        return f"{self.width}x{self.height}"

    @property
    def aspect_ratio(self) -> str:
        w, h = self.width, self.height
        if abs(w / h - 16 / 9) < 0.05:
            return "16:9"
        elif abs(w / h - 9 / 16) < 0.05:
            return "9:16"
        elif abs(w / h - 1) < 0.05:
            return "1:1"
        elif abs(w / h - 4 / 3) < 0.05:
            return "4:3"
        elif abs(w / h - 3 / 4) < 0.05:
            return "3:4"
        else:
            return f"{w}:{h}"

    @property
    def total_pixels(self) -> int:
        return self.width * self.height * self.batch_size

    @property
    def megapixels(self) -> float:
        return self.width * self.height / 1_000_000

    @property
    def is_video(self) -> bool:
        video_models = ["Sora", "Kling", "Veo", "LTX", "Mochi", "Hunyuan", "AnimateDiff", "CogVideoX", "Stable-Video"]
        return any(vm in self.model for vm in video_models)

    @property
    def estimated_time_seconds(self) -> float:
        base_time = 2.0
        resolution_factor = (self.width * self.height) / (1024 * 1024)
        step_factor = self.num_steps / 20
        if self.is_video:
            return base_time * resolution_factor * step_factor * 10 * self.batch_size
        return base_time * resolution_factor * step_factor * self.batch_size


@dataclass
class GenerationResult:
    """Result of a generation."""
    request_id: str
    model: str
    prompt: str
    output_path: str
    width: int
    height: int
    seed: int
    elapsed: float
    quality_score: float = 0.0

    @property
    def file_size_estimate(self) -> int:
        if self.output_path.endswith(".mp4"):
            return int(self.width * self.height * 30 * 2 / 8)
        return int(self.width * self.height * 3 / 8)

    @property
    def megapixels(self) -> float:
        return self.width * self.height / 1_000_000

    @staticmethod
    def compute_quality_score(elapsed: float, expected: float) -> float:
        if expected <= 0:
            return 0.0
        efficiency = expected / elapsed if elapsed > 0 else 0.0
        return min(1.0, efficiency)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "model": self.model,
            "prompt": self.prompt,
            "output_path": self.output_path,
            "resolution": f"{self.width}x{self.height}",
            "seed": self.seed,
            "elapsed": self.elapsed,
            "quality_score": self.quality_score,
        }


@dataclass
class ModelRouter:
    """Multi-model routing system."""
    available_models: list[str] = field(default_factory=lambda: list(MODEL_CATALOG))

    def get_models_by_type(self, model_type: str) -> list[str]:
        if model_type == "image":
            image_models = ["Flux", "Midjourney", "SDXL", "SD-3.5", "Ideogram", "Playground", "PixArt"]
            return [m for m in self.available_models if any(im in m for im in image_models)]
        elif model_type == "video":
            video_models = ["Sora", "Kling", "Veo", "LTX", "Mochi", "Hunyuan", "AnimateDiff", "CogVideoX", "Stable-Video"]
            return [m for m in self.available_models if any(vm in m for vm in video_models)]
        return []

    @staticmethod
    def estimate_model_speed(model: str, steps: int) -> float:
        speed_map = {
            "Flux.1-schnell": 1.0,
            "Flux.1-dev": 0.5,
            "Flux.1-Pro": 0.3,
            "Midjourney-v6": 0.8,
            "SDXL-Turbo": 1.5,
            "SDXL": 0.6,
            "Sora-OpenAI": 0.1,
            "Sora-2": 0.2,
            "Veo-3": 0.15,
            "Kling-2.5": 0.2,
        }
        base = speed_map.get(model, 0.5)
        return base * (20 / max(steps, 1))

    @staticmethod
    def recommend_model(prompt: str, use_case: str = "image") -> str:
        prompt_lower = prompt.lower()
        if use_case == "video":
            if "cinematic" in prompt_lower or "movie" in prompt_lower:
                return "Sora-2"
            elif "fast" in prompt_lower or "quick" in prompt_lower:
                return "LTX-Video"
            else:
                return "Kling-2.5"
        elif "portrait" in prompt_lower or "people" in prompt_lower:
            return "Midjourney-niji-6"
        elif "fast" in prompt_lower or "quick" in prompt_lower:
            return "Flux.1-schnell"
        elif "high quality" in prompt_lower or "professional" in prompt_lower:
            return "Flux.1-Pro"
        else:
            return "Flux.1-dev"

    @staticmethod
    def model_capabilities(model: str) -> dict[str, Any]:
        is_video = any(vm in model for vm in ["Sora", "Kling", "Veo", "LTX", "Mochi", "Hunyuan", "AnimateDiff", "CogVideoX", "Stable-Video"])
        return {
            "model": model,
            "type": "video" if is_video else "image",
            "supports_negative_prompt": True,
            "max_resolution": 2048 if "Pro" in model or "Midjourney" in model else 1024,
        }

    def route_request(self, request: GenerationRequest) -> str:
        if request.model in self.available_models:
            return request.model
        return ModelRouter.recommend_model(request.prompt, "video" if request.is_video else "image")

    @property
    def model_count(self) -> int:
        return len(self.available_models)

    def model_count_by_type(self, model_type: str) -> int:
        return len(self.get_models_by_type(model_type))


@dataclass
class PromptEnhancer:
    """Prompt enhancement for generative models."""
    @staticmethod
    def enhance(prompt: str, style: str = "photographic") -> str:
        if not prompt:
            return prompt
        enhanced = prompt.strip()
        style_descriptors = {
            "photographic": "photorealistic, high detail, 8k, professional photography, sharp focus",
            "cinematic": "cinematic lighting, film grain, 35mm, color graded, dramatic composition",
            "artistic": "oil painting style, brush strokes, artistic, museum quality",
            "anime": "anime style, vibrant colors, studio ghibli inspired, detailed line art",
            "digital": "digital art, concept art, trending on artstation, highly detailed",
            "3d": "3D render, octane render, ray tracing, volumetric lighting",
        }
        descriptor = style_descriptors.get(style, "")
        if descriptor:
            enhanced = f"{enhanced}, {descriptor}"
        return enhanced

    @staticmethod
    def negative_prompt(style: str = "photographic") -> str:
        negative_map = {
            "photographic": "blurry, low quality, deformed, distorted, watermark, text artifacts",
            "cinematic": "flat lighting, amateur, blur, bad composition, low resolution",
            "anime": "realistic, photo, 3d render, blurry, low detail",
            "digital": "blurry, low detail, watermark, text artifacts",
        }
        return negative_map.get(style, "blurry, low quality, deformed, distorted")

    @staticmethod
    def prompt_weight(prompt: str, word: str) -> float:
        if not prompt or not word:
            return 0.0
        words = prompt.lower().split()
        total = len(words)
        if total == 0:
            return 0.0
        count = sum(1 for w in words if word.lower() in w)
        return count / total

    @staticmethod
    def split_prompt_weights(prompt: str) -> dict[str, float]:
        if not prompt:
            return {}
        words = re.findall(r'(\(.*?\))|(\[.*?\])|(\w+)', prompt)
        result = {}
        for group in words:
            token = group[0] or group[1] or group[2]
            if token:
                result[token] = 1.0
        return result

    @staticmethod
    def style_transfer_prompt(content: str, style: str) -> str:
        return f"{content}, {style} style"


@dataclass
class LocalInferenceEngine:
    """Local inference engine concepts."""
    @staticmethod
    def memory_requirement_mb(model: str, resolution: int = 1024) -> float:
        base_map = {
            "Flux.1-dev": 8000,
            "Flux.1-schnell": 6000,
            "Flux.1-Pro": 12000,
            "Midjourney-v6": 8000,
            "SDXL": 4000,
            "SDXL-Turbo": 4000,
            "SD-3.5": 6000,
            "Sora-OpenAI": 16000,
            "Kling-2.5": 12000,
            "Veo-3": 16000,
        }
        base = base_map.get(model, 5000)
        scale = (resolution / 1024) ** 2
        return base * scale

    @staticmethod
    def gpu_requirement(model: str) -> str:
        if "Flux.1-Pro" in model or "Sora" in model or "Veo" in model:
            return "H100 80GB"
        elif "Flux.1-dev" in model or "Midjourney" in model or "Kling" in model:
            return "A100 40GB"
        elif "SDXL" in model or "SD-3.5" in model:
            return "RTX 4090"
        else:
            return "RTX 3060"

    @staticmethod
    def generation_speed(model: str, steps: int = 20) -> float:
        speed_map = {
            "Flux.1-schnell": 0.5,
            "Flux.1-dev": 1.5,
            "SDXL-Turbo": 0.3,
            "SDXL": 1.0,
            "SD-3.5": 1.2,
        }
        return speed_map.get(model, 1.0) * (steps / 20)

    @staticmethod
    def batch_processing_time(model: str, batch_size: int, steps: int = 20) -> float:
        per_image = LocalInferenceEngine.generation_speed(model, steps)
        return per_image * batch_size

    @staticmethod
    def disk_space_gb(model: str, outputs: int) -> float:
        base_map = {
            "Flux.1-dev": 10,
            "Midjourney-v6": 8,
            "SDXL": 5,
            "Sora-2": 20,
        }
        base = base_map.get(model, 5)
        return base + outputs * 0.01

    @staticmethod
    def energy_consumption_kwh(model: str, steps: int = 20) -> float:
        watt_map = {
            "Flux.1-dev": 300,
            "SDXL": 200,
            "SDXL-Turbo": 250,
            "Sora-2": 500,
            "Kling-2.5": 400,
        }
        watts = watt_map.get(model, 250)
        hours = steps * 0.05
        return watts * hours / 1000


@dataclass
class GenerationPipeline:
    """End-to-end generation pipeline."""
    @staticmethod
    def preprocess_request(request: GenerationRequest, style: str = "photographic") -> GenerationRequest:
        enhanced_prompt = PromptEnhancer.enhance(request.prompt, style)
        negative = PromptEnhancer.negative_prompt(style)
        request.negative_prompt = negative
        request.prompt = enhanced_prompt
        return request

    @staticmethod
    def post_process_result(result: GenerationResult) -> GenerationResult:
        expected = result.elapsed * 0.8
        result.quality_score = GenerationResult.compute_quality_score(result.elapsed, expected)
        return result

    @staticmethod
    def pipeline_stats(results: list[GenerationResult]) -> dict[str, Any]:
        if not results:
            return {"total": 0, "avg_time": 0.0, "avg_quality": 0.0}
        total_time = sum(r.elapsed for r in results)
        avg_quality = sum(r.quality_score for r in results) / len(results)
        return {
            "total": len(results),
            "avg_time": total_time / len(results),
            "avg_quality": avg_quality,
            "models_used": len(set(r.model for r in results)),
        }

    @staticmethod
    def compare_results(r1: GenerationResult, r2: GenerationResult) -> dict[str, Any]:
        return {
            "faster": r1.elapsed < r2.elapsed,
            "better_quality": r1.quality_score > r2.quality_score,
            "resolution_advantage": r1.width * r1.height > r2.width * r2.height,
            "time_difference": abs(r1.elapsed - r2.elapsed),
            "quality_difference": abs(r1.quality_score - r2.quality_score),
        }


@dataclass
class MultiModelStudio:
    """Unified multi-model generation studio."""
    router: ModelRouter = field(default_factory=ModelRouter)
    results: list[GenerationResult] = field(default_factory=list)

    def generate(self, request: GenerationRequest) -> GenerationResult:
        model = self.router.route_request(request)
        expected_time = request.estimated_time_seconds
        elapsed = expected_time * 0.85
        result = GenerationResult(
            request_id=request.request_id,
            model=model,
            prompt=request.prompt,
            output_path=f"/outputs/{request.request_id}.{request.output_format}",
            width=request.width,
            height=request.height,
            seed=request.seed,
            elapsed=elapsed,
        )
        result.quality_score = GenerationResult.compute_quality_score(elapsed, expected_time)
        self.results.append(result)
        return result

    def generate_batch(self, requests: list[GenerationRequest]) -> list[GenerationResult]:
        results = []
        for req in requests:
            results.append(self.generate(req))
        return results

    def model_statistics(self) -> dict[str, Any]:
        by_model = defaultdict(list)
        for r in self.results:
            by_model[r.model].append(r)
        stats = {}
        for model, model_results in by_model.items():
            avg_time = sum(r.elapsed for r in model_results) / len(model_results)
            avg_quality = sum(r.quality_score for r in model_results) / len(model_results)
            stats[model] = {
                "count": len(model_results),
                "avg_time": avg_time,
                "avg_quality": avg_quality,
            }
        return stats

    @property
    def total_generations(self) -> int:
        return len(self.results)

    @property
    def unique_models_used(self) -> int:
        return len(set(r.model for r in self.results))

    @property
    def average_quality(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.quality_score for r in self.results) / len(self.results)

    def search_models(self, query: str) -> list[str]:
        query_lower = query.lower()
        return [m for m in self.router.available_models if query_lower in m.lower()]

    def studio_capabilities(self) -> dict[str, Any]:
        return {
            "total_models": self.router.model_count,
            "image_models": self.router.model_count_by_type("image"),
            "video_models": self.router.model_count_by_type("video"),
            "total_generations": self.total_generations,
            "unique_models_used": self.unique_models_used,
            "average_quality": self.average_quality,
        }
