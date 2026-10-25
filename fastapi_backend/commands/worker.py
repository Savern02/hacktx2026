"""The discovery worker: drains ingestion_jobs. Run it next to the API.

    python -m commands.worker            # WORKER_CONCURRENCY processes
    python -m commands.worker --once     # claim and run at most one job, then exit

Every SerpApi, page fetch and LLM call happens in this process, never in a web request.
"""

import argparse
import multiprocessing

from app.discovery.worker import live_deps_factory, run_forever
from commands._cli import async_session_maker, discovery_settings, run


def _loop(once: bool) -> None:
    make_deps = live_deps_factory(discovery_settings)
    run(lambda: run_forever(async_session_maker, make_deps, once=once))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    live_deps_factory(discovery_settings)  # fail fast on missing settings
    count = 1 if args.once else max(discovery_settings.WORKER_CONCURRENCY, 1)
    if count == 1:
        _loop(args.once)
        return
    # Scale by processes, not threads (Section 9).
    procs = [multiprocessing.Process(target=_loop, args=(False,)) for _ in range(count)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()


if __name__ == "__main__":
    main()
