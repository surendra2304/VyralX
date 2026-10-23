import subprocess
from pathlib import Path

# Let's test 3 genuinely attractive, NON-YELLOW styles:
# Style A: "Daily Dose Clean" - Bahnschrift (DIN modern), pure white text, sleek 3px soft black stroke, elegant 2px shadow
# Style B: "Aesthetic CapCut Glow" - Montserrat / Arial Black, pure white with cyan/ice-blue accent keyword, 3.5px crisp stroke
# Style C: "Modern Minimalist" - Segoe UI Semibold / Bold, pure white, clean outline, slightly elevated

def test_designs():
    # Style A: Daily Dose / Vox aesthetic - Pure clean white, modern Bahnschrift font, perfect spacing
    ass_a = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: CleanWhite,Bahnschrift,64,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,2,0,1,3.5,2.0,2,80,80,420,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:10.00,CleanWhite,,0,0,0,,SERVES HIM SOAP FOAM
"""
    Path("temp_a.ass").write_text(ass_a, encoding="utf-8")

    # Style B: Ice Cyan Accent - Crisp White with Ice-Cyan accent on punchline word
    ass_b = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: IceCyan,Arial Black,58,&H00FFFFFF,&H000000FF,&H00000000,&H90000000,1,0,0,0,100,100,1.5,0,1,4.0,2.0,2,80,80,420,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:10.00,IceCyan,,0,0,0,,SERVES HIM {\\c&H00FFFF80&}SOAP FOAM
"""
    Path("temp_b.ass").write_text(ass_b, encoding="utf-8")

    # Style C: Pure Elegant White - Montserrat with soft dark glow/shadow, no heavy jagged outline
    ass_c = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: SoftGlow,Montserrat,60,&H00FFFFFF,&H000000FF,&H00111111,&HAA000000,1,0,0,0,100,100,2,0,1,2.8,3.5,2,80,80,420,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:10.00,SoftGlow,,0,0,0,,SERVES HIM SOAP FOAM
"""
    Path("temp_c.ass").write_text(ass_c, encoding="utf-8")

    for letter in ['a', 'b', 'c']:
        cmd = [
            "ffmpeg", "-hide_banner", "-y",
            "-ss", "00:00:04.0",
            "-i", "media/viral_sources/A_Q2qpbHrqo.mp4",
            "-vf", f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,subtitles=temp_{letter}.ass",
            "-vframes", "1", f"clean_style_{letter}.jpg"
        ]
        subprocess.run(cmd, check=True)
    print("Clean styles rendered")

if __name__ == "__main__":
    test_designs()
