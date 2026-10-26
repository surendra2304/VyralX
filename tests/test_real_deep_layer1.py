"""Tests for MoneyPrinterTurbo implementation."""

from __future__ import annotations

import sys
from pathlib import Path

# Add VyralX to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.real_money_printer import (
    MoneyPrinterScriptGenerator,
    MoneyPrinterVideoAssembler,
    MoneyPrinterPipeline,
    VideoSegment,
    VideoProject,
    ScriptChunk,
)


def test_video_segment():
    """Test VideoSegment creation and properties."""
    segment = VideoSegment(
        segment_id="seg_0",
        index=0,
        text="This is a test video segment.",
        duration=30.0,
    )

    assert segment.segment_id == "seg_0"
    assert segment.index == 0
    assert segment.word_count == 6
    assert not segment.is_ready

    segment.status = "completed"
    segment.image_url = "https://example.com/image.jpg"
    segment.audio_url = "https://example.com/audio.mp3"
    assert segment.is_ready

    result = segment.to_dict()
    assert "seg_0" in result["segment_id"]
    assert "duration" in result


def test_video_project():
    """Test VideoProject creation and properties."""
    project = VideoProject(
        project_id="mp_123",
        topic="Cryptocurrency Trading",
        keywords=["crypto", "trading", "bitcoin"],
        language="en",
        aspect_ratio="9:16",
    )

    assert project.project_id == "mp_123"
    assert project.topic == "Cryptocurrency Trading"
    assert len(project.keywords) == 3
    assert project.total_segments == 0

    # Add segments
    for i in range(3):
        segment = VideoSegment(
            segment_id=f"seg_{i}",
            index=i,
            text=f"Segment {i}",
            duration=30.0,
        )
        project.add_segment(segment)

    assert project.total_segments == 3
    assert project.total_duration == 90.0

    result = project.to_dict()
    assert "mp_123" in result["project_id"]
    assert "total_duration" in result


def test_script_chunk():
    """Test ScriptChunk creation and properties."""
    chunk = ScriptChunk(
        text="This is a test script chunk with several words.",
        keywords=["test", "script"],
        estimated_duration=30.0,
        visual_suggestion="Test visual",
    )

    assert chunk.word_count == 9
    assert chunk.reading_time > 0

    result = chunk.to_dict()
    assert "text" in result
    assert "reading_time" in result


def test_script_generator():
    """Test MoneyPrinterScriptGenerator."""
    generator = MoneyPrinterScriptGenerator()

    chunks = generator.generate_script(
        topic="Artificial Intelligence",
        keywords=["AI", "machine learning", "neural networks"],
        language="en",
    )

    assert len(chunks) > 0
    assert all(isinstance(c, ScriptChunk) for c in chunks)
    assert all(c.text for c in chunks)
    assert all(c.estimated_duration > 0 for c in chunks)

    total_duration = generator.estimate_total_duration(chunks)
    assert total_duration > 0


def test_video_assembler():
    """Test MoneyPrinterVideoAssembler."""
    assembler = MoneyPrinterVideoAssembler()

    # Test subtitle timing
    text = "This is a test subtitle with multiple words."
    duration = 10.0
    subtitles = assembler.calculate_subtitle_timing(text, duration)

    assert len(subtitles) > 0
    assert all("start" in s and "end" in s and "text" in s for s in subtitles)

    # Test voiceover prompt
    prompt = assembler.generate_voiceover_prompt("Test text", "en")
    assert "voiceover" in prompt

    # Test segment duration
    duration = assembler.estimate_segment_duration("This is a test text.")
    assert duration > 0

    # Test background music
    bgm = assembler.select_background_music("lofi")
    assert "name" in bgm
    assert "mood" in bgm
    assert "bpm" in bgm


def test_pipeline():
    """Test MoneyPrinterPipeline."""
    from app.agents.real_money_printer import MoneyPrinterPipeline

    config = MoneyPrinterPipeline.PipelineConfig(
        topic="Stock Market Investing",
        keywords=["stocks", "investing", "portfolio"],
        language="en",
        aspect_ratio="16:9",
        bgm_genre="upbeat",
        num_segments=5,
    )

    pipeline = MoneyPrinterPipeline(config)

    # Generate script
    chunks = pipeline.generate_script()
    assert len(chunks) > 0
    assert all(isinstance(c, ScriptChunk) for c in chunks)

    # Create project
    project = pipeline.create_project()
    assert project.project_id.startswith("mp_")
    assert project.total_segments > 0

    # Generate segments
    segments = pipeline.generate_segments()
    assert len(segments) == project.total_segments
    assert all(s.is_ready for s in segments)

    # Assemble video
    result = pipeline.assemble_video()
    assert "project" in result
    assert "background_music" in result
    assert "subtitle_count" in result
    assert result["project"]["status"] == "completed"

    # Get status
    status = pipeline.get_project_status()
    assert status["status"] == "completed"
    assert status["output_url"] != ""


def test_pipeline_auto_keywords():
    """Test pipeline auto-generates keywords when none provided."""
    from app.agents.real_money_printer import MoneyPrinterPipeline

    config = MoneyPrinterPipeline.PipelineConfig(
        topic="Cryptocurrency",
        keywords=[],
        language="en",
        num_segments=3,
    )

    pipeline = MoneyPrinterPipeline(config)
    chunks = pipeline.generate_script()

    assert len(chunks) > 0
    assert len(config.keywords) > 0


def test_pipeline_chinese():
    """Test pipeline with Chinese language."""
    from app.agents.real_money_printer import MoneyPrinterPipeline

    config = MoneyPrinterPipeline.PipelineConfig(
        topic="加密货币交易",
        keywords=["加密货币", "交易", "比特币"],
        language="zh",
    )

    pipeline = MoneyPrinterPipeline(config)
    chunks = pipeline.generate_script()

    assert len(chunks) > 0
    assert all(c.text for c in chunks)


def test_video_project_completion():
    """Test VideoProject completion tracking."""
    project = VideoProject(
        project_id="mp_test",
        topic="Test Topic",
    )

    # Add segments
    for i in range(3):
        segment = VideoSegment(
            segment_id=f"seg_{i}",
            index=i,
            text=f"Segment {i}",
            duration=30.0,
        )
        project.add_segment(segment)

    assert project.completed_segments == 0

    # Mark segments as completed
    for segment in project.segments:
        segment.status = "completed"
        segment.image_url = "https://example.com/image.jpg"
        segment.audio_url = "https://example.com/audio.mp3"

    assert project.completed_segments == 3
    assert project.total_segments == 3


def test_subtitle_timing():
    """Test subtitle timing calculation."""
    assembler = MoneyPrinterVideoAssembler()

    text = "This is a longer text that should produce multiple subtitle chunks."
    duration = 15.0
    subtitles = assembler.calculate_subtitle_timing(text, duration)

    assert len(subtitles) >= 2
    assert subtitles[0]["start"] == 0.0
    assert subtitles[-1]["end"] <= duration

    # Check subtitles are sequential
    for i in range(len(subtitles) - 1):
        assert subtitles[i]["end"] >= subtitles[i + 1]["start"]
