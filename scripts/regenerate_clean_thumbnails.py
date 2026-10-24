"""Regenerates pristine, high-CTR viral thumbnails from clean raw sources (ZERO burnt subtitles)."""
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.thumbnail_designer import generate_genre_thumbnail  # noqa: E402

TITLE_MAP = {
    "A_Q2qpbHrqo": ("The $9,999,999 Michelin Restaurant", "COMEDY"),
    "hx265ujsLVU": ("Maximum Main Character Energy In School", "RESPECT"),
    "bS_CSAPHjUY": ("How To Open A Can With Concrete", "SURVIVAL"),
    "JjuQ2ink05Q": ("Most Satisfying Kinetic Sand Slicing", "SATISFYING"),
    "sOZrJUkCLYU": ("Survival Bushcraft Life Hack", "SURVIVAL"),
    "BmW5Qb3fqlk": ("Extreme Precision Balance Trick", "PRECISION"),
    "heI4DLab-l8": ("Mind-Blowing Optical Illusion", "CRAFT"),
    "k--pkJcePTM": ("Hypnotic Mechanical Precision", "SATISFYING"),
    "mHE8rDhCWAw": ("Unexpected Comedy Plot Twist", "COMEDY"),
}

def main():
    source_dir = Path("media/viral_sources")
    edited_dir = Path("media/edited_videos")
    edited_dir.mkdir(parents=True, exist_ok=True)
    
    print("=== REGENERATING CLEAN HIGH-CTR THUMBNAILS (ZERO BURNT SUBTITLES) ===")
    for vid, (headline, genre) in TITLE_MAP.items():
        raw_source = source_dir / f"{vid}.mp4"
        if not raw_source.exists():
            print(f"Skipping {vid}: raw source not found at {raw_source}")
            continue
        
        thumb_out = edited_dir / f"vyralx-commentary-{vid}-thumbnail.jpg"
        print(f"Generating clean thumbnail for {vid} ({headline}) from RAW SOURCE...")
        generate_genre_thumbnail(
            video_path=raw_source,
            output_path=thumb_out,
            headline=headline,
            category=genre,
        )
        print(f"-> Saved: {thumb_out.name} ({thumb_out.stat().st_size / 1024:.1f} KB)")

if __name__ == "__main__":
    main()
