import argparse
import os
import sys

sys.path.append(os.path.abspath(os.path.join(__file__, "..", "..")))

from epub_translator.webui import WebUIServer


def main() -> None:
    parser = argparse.ArgumentParser(description="Start EPUB Translator Web UI")
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=2527,
        help="Port to bind to (default: 2527)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default="out",
        help="Output directory for translations (default: out)",
    )
    args = parser.parse_args()

    server = WebUIServer(
        host=args.host,
        port=args.port,
        output_dir=args.output,
    )
    server.start()


if __name__ == "__main__":
    main()
