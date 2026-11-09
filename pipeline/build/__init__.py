"""Build the build layer: UN Geodata cut into units that dissolve to UN or GAUL."""

from argparse import ArgumentParser
from importlib import import_module

from .common import STAGES

DEFAULT_STAGES = ("01", "02", "03", "04", "05", "06", "08")


def main() -> None:
    """Run every stage but 00 and 07, one ``--stage``, or all ``--from`` a stage."""
    parser = ArgumentParser()
    parser.add_argument("--stage", choices=STAGES)
    parser.add_argument("--from", dest="start", choices=DEFAULT_STAGES)
    args, _ = parser.parse_known_args()
    rest = DEFAULT_STAGES[DEFAULT_STAGES.index(args.start or "01") :]
    for stage in [args.stage] if args.stage else rest:
        import_module(f"pipeline.build._{stage}_{STAGES[stage]}").main()
