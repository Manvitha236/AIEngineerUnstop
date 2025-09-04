"""CLI utility to wipe & load the support emails dataset into the local database.

Usage (PowerShell):
  python -m backend.app.scripts.load_dataset -p 68b1acd44f393_Sample_Support_Emails_Dataset.csv --generate

By default it wipes existing emails. Omit --no-wipe to keep existing and append.
"""
import argparse
import os
from pathlib import Path

from ..db.database import SessionLocal, ensure_schema  # type: ignore
from ..services.dataset_loader import load_dataset


def main():
    parser = argparse.ArgumentParser(description="Load support emails dataset into DB")
    parser.add_argument("-p", "--path", dest="path", required=False, default=os.getenv("DATASET_CSV_PATH", "68b1acd44f393_Sample_Support_Emails_Dataset.csv"), help="Path to CSV dataset")
    parser.add_argument("--generate", action="store_true", help="Queue auto-response generation for each email")
    parser.add_argument("--no-wipe", action="store_true", help="Do not delete existing emails (append instead)")
    args = parser.parse_args()

    csv_path = Path(args.path)
    if not csv_path.exists():
        raise SystemExit(f"Dataset file not found: {csv_path}")

    ensure_schema()
    session = SessionLocal()
    try:
        summary = load_dataset(
            session,
            str(csv_path),
            generate_responses=args.generate,
            wipe=not args.no_wipe,
        )
        print("Dataset load summary:")
        for k, v in summary.items():
            print(f"  {k}: {v}")
    finally:
        session.close()


if __name__ == "__main__":  # pragma: no cover
    main()
