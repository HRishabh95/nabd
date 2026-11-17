"""`nabd doctor` checks the environment; `nabd serve` runs the API."""

import argparse
import sys


def main(argv=None):
    p = argparse.ArgumentParser(prog="nabd")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor", help="check the environment")
    sd = sub.add_parser("seed", help="download open data and run every model once (idempotent)")
    sd.add_argument("--full", action="store_true", help="also fetch 30 days of news and the weekly history since 2019 (~1 GB)")
    sv = sub.add_parser("serve", help="run the API")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--reload", action="store_true")
    args = p.parse_args(argv)

    if args.cmd == "doctor":
        from .core.doctor import checks

        marks = {"ok": "✓", "warn": "!", "fail": "✗"}
        results = checks()
        for c in results:
            line = f" {marks[c['level']]} {c['name']:<16} {c['detail']}"
            if c["level"] != "ok" and c["fix"]:
                line += f"\n   → {c['fix']}"
            print(line)
        return 0 if all(c["ok"] for c in results) else 1
    if args.cmd == "seed":
        from .seed import seed
        return seed(full=args.full)
    if args.cmd == "serve":
        import uvicorn

        # SSE streams never end on their own; without a limit uvicorn would wait for them forever on shutdown
        uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, reload=args.reload,
                    timeout_graceful_shutdown=3)
        return 0


if __name__ == "__main__":
    sys.exit(main())
