from __future__ import annotations

import argparse
import importlib
from typing import Callable, Dict


def _load_main(dotted: str) -> Callable[[], int]:
    """
    Load a `main()` function from a dotted module path.

    We keep this indirection so `oce` can act as a thin wrapper over the
    existing `python -m <package>.<module>` entrypoints.
    """
    mod = importlib.import_module(dotted)
    main = getattr(mod, "main", None)
    if not callable(main):
        raise SystemExit(f"Expected callable main() in module: {dotted}")
    return main


COMMANDS: Dict[str, str] = {
    # DB
    "migrate": "db.apply_migrations",
    # Importers / seeders
    "import-sources": "importer.import_sources",
    "seed-osce-marking": "importer.seed_osce_marking_primitives",
    "seed-cpte-rubric": "importer.create_cpte_training_rubric",
    "generate-dutton-cases": "importer.generate_osce_cases_from_dutton",
    # Export
    "export-json": "exporter.export_to_json",
    # Examiner writeback
    "apply-marksheet": "examiner.apply_marksheet",
    # Station runtime + enforcement (for testers)
    "station": "runtime.station_cli",
    "enforce-station": "runtime.enforce_station",
    "backfill-allowed-actions": "runtime.backfill_allowed_actions",
    # Web API
    "serve": "web.serve",
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="oce",
        description="OCE OSCE simulator CLI (wrapper around repo modules).",
    )
    p.add_argument(
        "command",
        choices=sorted(COMMANDS.keys()),
        help="Which command to run",
    )
    p.add_argument(
        "args",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded to the underlying module",
    )
    return p


def main() -> int:
    p = build_parser()
    ns = p.parse_args()

    # Reconstruct argv for the delegated module:
    # - the underlying module uses argparse and expects sys.argv to include program name
    import sys

    sys.argv = [f"python -m {COMMANDS[ns.command]}", *ns.args]
    delegated_main = _load_main(COMMANDS[ns.command])
    return int(delegated_main())


if __name__ == "__main__":
    raise SystemExit(main())

