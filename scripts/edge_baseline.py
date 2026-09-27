"""Render the old Edge-TTS route with first-byte timing, from a stdin request."""
import asyncio
import json
import sys
import time
from pathlib import Path

import edge_tts


async def main():
    request = json.load(sys.stdin)
    started, first, boundaries = time.perf_counter(), None, []
    communicate = edge_tts.Communicate(request["text"], request["voice"], rate=f'{request.get("rate",0):+d}%', volume=f'{request.get("volume",0):+d}%', pitch=f'{request.get("pitch",0):+d}Hz', boundary="WordBoundary")
    with Path(request["out"]).open("xb") as f:
        async for event in communicate.stream():
            if event["type"] == "audio":
                if first is None:
                    first = time.perf_counter() - started
                f.write(event["data"])
            elif event["type"] == "WordBoundary":
                boundaries.append({"time": event["offset"]/10_000_000, "duration": event["duration"]/10_000_000})
    print(json.dumps({"provider": "edge-tts", "voice": request["voice"], "first_audio_seconds": first, "provider_total_seconds": time.perf_counter()-started, "word_timestamps": True, "word_boundary_count": len(boundaries)}))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__}))
        raise SystemExit(1)
