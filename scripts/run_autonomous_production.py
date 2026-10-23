"""VyralX Production Pipeline Execution Script.

Produces transformative commentary shorts for top viral visual clips:
- bS_CSAPHjUY: The Concrete Can Opener Lifehack (318M views)
- JjuQ2ink05Q: Most Oddly Satisfying Moments (593M views)
- sOZrJUkCLYU: The Craziest Unexpected Twist (750M views)
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.autonomous_pipeline import VideoJob, run_pipeline

sys.stdout.reconfigure(encoding="utf-8")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("vyralx.run")

PRODUCTION_JOBS = [
    VideoJob(
        video_id="bS_CSAPHjUY",
        source_file=Path("media/viral_sources/bS_CSAPHjUY.mp4"),
        title_concept="How To Open A Can With Just Concrete 🏕️🥫 #Shorts",
        script=(
            "If you are ever trapped in the wild with canned food and no can opener, do not panic. "
            "Instead of trying to smash it with a rock and spilling everything, find a rough concrete slab. "
            "Turn the can upside down and rub the rim vigorously against the stone for twenty seconds. "
            "The friction wears down the outer seal instantly. "
            "Give the sides a gentle squeeze, and the lid pops right off. "
            "That is a survival life hack that might actually save your life."
        ),
        cyan_keywords={
            "TRAPPED", "WILD", "CANNED", "FOOD", "OPENER", "PANIC", "SMASH", "ROCK",
            "CONCRETE", "SLAB", "STONE", "FRICTION", "SEAL", "INSTANTLY", "POPS",
            "SURVIVAL", "HACK", "LIFE"
        },
        category_id="24",
        debate_question="Did you know about this concrete trick before watching this? YES or NO? 👇",
        tags=["shorts", "survival", "lifehacks", "bushcraft", "camping", "diy", "smart hacks", "outdoor survival", "viral shorts"]
    ),
    VideoJob(
        video_id="JjuQ2ink05Q",
        source_file=Path("media/viral_sources/JjuQ2ink05Q.mp4"),
        title_concept="The Most Satisfying Video On The Internet 🤤✨ #Shorts",
        script=(
            "This might be the single most oddly satisfying video on the entire internet. "
            "From razor-sharp blades slicing through kinetic sand to millimeter-perfect liquid flow, "
            "every single second resets your brain. "
            "There is something completely hypnotic about watching pure geometric perfection in motion. "
            "Do not even try to deny it, you are already watching this for the second time."
        ),
        cyan_keywords={
            "ODDLY", "SATISFYING", "INTERNET", "RAZOR-SHARP", "BLADES", "SLICING",
            "KINETIC", "SAND", "MILLIMETER-PERFECT", "LIQUID", "FLOW", "RESETS",
            "BRAIN", "HYPNOTIC", "GEOMETRIC", "PERFECTION", "SECOND", "TIME"
        },
        category_id="24",
        debate_question="On a scale of 1 to 10, how satisfying was this? Be honest! 👇",
        tags=["shorts", "satisfying", "oddly satisfying", "kinetic sand", "relaxing", "visual art", "trending shorts", "viral"]
    ),
    VideoJob(
        video_id="sOZrJUkCLYU",
        source_file=Path("media/viral_sources/sOZrJUkCLYU.mp4"),
        title_concept="Wait For The Unexpected Twist 🤯💀 #Shorts",
        script=(
            "Wait until the very last second because you are definitely not going to see this plot twist coming. "
            "Just when you think you understand exactly what is happening, reality takes a sharp left turn "
            "and leaves everyone completely speechless. "
            "That is a masterclass in unexpected comedic timing."
        ),
        cyan_keywords={
            "SECOND", "PLOT", "TWIST", "REALITY", "SHARP", "SPEECHLESS",
            "MASTERCLASS", "UNEXPECTED", "COMEDIC", "TIMING"
        },
        category_id="24",
        trim_duration=19.0,
        debate_question="Did you see that ending coming or did it fool you? 😂👇",
        tags=["shorts", "plot twist", "funny", "unexpected", "comedy", "viral shorts", "lol", "humor"]
    )
]

def main():
    log.info("Starting VyralX Autonomous Production Pipeline...")
    results = run_pipeline(PRODUCTION_JOBS)
    log.info("Production complete! Results: %s", results)

if __name__ == "__main__":
    main()
