"""Run the pipeline steps in order."""

from argparse import ArgumentParser
from importlib import import_module
from logging import INFO, basicConfig
from os import getenv

STEPS = ("download", "prepare", "extend", "attributes", "tiles")
OPTIONAL_STEPS = ("fieldmaps", "register", "differences", "catalog")

basicConfig(
    level=INFO,
    format="%(asctime)s - %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
parser = ArgumentParser(description="Build the ADM0 differences register.")
parser.add_argument("--step", default=getenv("STEP"), choices=STEPS + OPTIONAL_STEPS)
args, _ = parser.parse_known_args()

for step in [args.step] if args.step else STEPS:
    import_module(f"pipeline.{step}").main()
