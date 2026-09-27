"""Narrow compatibility entry for the old SpeechKitTtsService in test builds."""
import sys
from .adapters import selected_voice
from .cli import main


def run():
    args = sys.argv[1:]
    if "tts" in args:
        args.remove("tts")
    if "--voice" in args:
        i = args.index("--voice") + 1
        args[i] = selected_voice("", args[i])
    return main(args)


if __name__ == "__main__":
    raise SystemExit(run())
