"""Phase 4A read-only bounded corpus validation; local outputs remain ignored."""
from pathlib import Path
import argparse
import _common
from quantbot.options.validation import run_validation


def main():
    """Require explicit dataset, output and model assumptions."""
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-root',type=Path,required=True)
    p.add_argument('--corpus-manifest',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--rate',type=float,required=True)
    p.add_argument('--dividend-yield',type=float,required=True)
    a=p.parse_args()
    report=run_validation(a.data_root,a.corpus_manifest,a.output,rate=a.rate,
        dividend_yield=a.dividend_yield,repo=Path(__file__).resolve().parents[1])
    print(report['run_id'])
    print(report['comparison']['statuses'])
    print(report['comparison']['iv_comparison'])


if __name__=='__main__':main()
