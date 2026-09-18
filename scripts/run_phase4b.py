"""Run the approved frozen S05 specification offline; no parameter overrides."""
import argparse
from pathlib import Path
import _common
from quantbot.research.phase4b import run_research


def main():
    """Require explicit immutable data locations and a new ignored output path."""
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root',type=Path,required=True)
    parser.add_argument('--underlying-sources',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    repo=Path(__file__).resolve().parents[1]
    run_research(repo,args.data_root,repo/'research/phase4b/s05-v1/specification.json',
                 args.underlying_sources,args.output)


if __name__=='__main__':main()