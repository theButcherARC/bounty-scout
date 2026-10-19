#!/usr/bin/env python3
"""Record a live Bounty Scout run as a terminal-style demo video.

Runs scout.py, captures output line-by-line, renders terminal frames with PIL,
encodes to mp4 with ffmpeg. Shows the real model-backed run in real time.
"""
import os
import subprocess
import sys
import time
from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1280, 720
BG = (18, 18, 28)
FG = (220, 220, 230)
GREEN = (120, 220, 130)
YELLOW = (230, 200, 120)
FPS = 1  # 1 fps: each terminal state holds 1s, good for demo pacing
FONT_SIZE = 20
LINE_H = 26
TOP_MARGIN = 30
LEFT_MARGIN = 25
MAX_LINES = 22

try:
    FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", FONT_SIZE)
except OSError:
    FONT = ImageFont.load_default()

HEADER = "bounty-scout demo  |  OpenMinion 0.1 SDK  |  live model run"


def render_frame(lines, header=HEADER):
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    d = ImageDraw.Draw(img)
    d.text((LEFT_MARGIN, 8), header, font=FONT, fill=YELLOW)
    d.line([(0, 34), (WIDTH, 34)], fill=(60, 60, 80), width=1)
    y = TOP_MARGIN + 14
    for line in lines[-MAX_LINES:]:
        color = GREEN if line.startswith("[") or line.startswith("SCORE") else FG
        d.text((LEFT_MARGIN, y), line[:110], font=FONT, fill=color)
        y += LINE_H
    return img


def main():
    out_dir = os.path.dirname(os.path.abspath(__file__))
    frames_dir = os.path.join(out_dir, "video_frames")
    os.makedirs(frames_dir, exist_ok=True)
    video_path = os.path.join(out_dir, "demo.mp4")

    env = dict(os.environ)
    env["OPENAI_COMPATIBLE_API_KEY"] = "none"
    env["no_proxy"] = "localhost,127.0.0.1"
    env["NO_PROXY"] = "localhost,127.0.0.1"

    venv_python = os.path.join(out_dir, ".venv", "bin", "python")
    proc = subprocess.Popen(
        [venv_python, "-u", os.path.join(out_dir, "scout.py")],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, cwd=out_dir, env=env,
    )

    lines = ["$ python scout.py", ""]
    frame_idx = 0

    def save_frame(n=1):
        nonlocal frame_idx
        for _ in range(n):
            img = render_frame(lines)
            img.save(os.path.join(frames_dir, f"f{frame_idx:05d}.png"))
            frame_idx += 1

    # Title card: hold 4s
    lines = ["", "", "  BOUNTY SCOUT", "", "  An OpenMinion 0.1 SDK agent that reads a bounty", "  listing and scores it for a vibe-coder profile.", "", "  Live model-backed run..."]
    save_frame(8)

    lines = ["$ python scout.py", ""]
    save_frame(2)

    for raw in proc.stdout:
        line = raw.rstrip("\n")
        lines.append(line)
        # Hold each new line 3s so the viewer can read it
        save_frame(8)

    proc.wait()
    lines.append("")
    lines.append(f"[exit code {proc.returncode}]")
    save_frame(8)

    # End card: show the saved report, hold 6s
    try:
        import glob
        reports = sorted(glob.glob(os.path.join(out_dir, "reports", "*.md")))
        if reports:
            with open(reports[-1]) as f:
                report_lines = ["", "  SAVED REPORT: " + os.path.basename(reports[-1]), ""]
                for rl in f.read().split("\n")[:12]:
                    report_lines.append("  " + rl[:100])
                lines = report_lines
                save_frame(8)
    except Exception:
        pass

    print(f"rendered {frame_idx} frames", flush=True)

    # Encode with ffmpeg
    cmd = [
        "ffmpeg", "-y", "-framerate", str(FPS),
        "-i", os.path.join(frames_dir, "f%05d.png"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23",
        video_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("ffmpeg failed:", r.stderr[-500:], flush=True)
        sys.exit(1)
    size = os.path.getsize(video_path)
    dur = frame_idx / FPS
    print(f"video saved: {video_path} ({size/1e6:.1f} MB, ~{dur:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
