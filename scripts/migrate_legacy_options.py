"""Controlled legacy inventory/migration. No network and no writes to legacy root."""
import argparse
from pathlib import Path
import _common  # noqa: F401

from quantbot.data.legacy_corpus import save_inventory, migrate_corpus
from quantbot.data.storage import DataStore

def main():
    """Inventory first, then migrate only the recorded bounded corpus."""
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root",type=Path,default=None)
    subs=parser.add_subparsers(dest="command",required=True)
    inv=subs.add_parser("inventory")
    inv.add_argument("--legacy-root",type=Path,required=True)
    inv.add_argument("--audit-name",default="phase2c_inventory")
    mig=subs.add_parser("migrate")
    mig.add_argument("--inventory",type=Path,required=True)
    args=parser.parse_args()
    store=DataStore(args.data_root)
    if args.command=="inventory":
        from quantbot.data.storage.provenance import component
        print(save_inventory(args.legacy_root,store.root/"audits"/component(args.audit_name)))
    else:
        print(migrate_corpus(store,args.inventory))

if __name__=="__main__":
    main()
