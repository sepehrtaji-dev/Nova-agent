from pathlib import Path

import pyarrow.parquet as pq


REPO = "HuggingFaceFW/fineweb-edu"
FILE = "sample/10BT/013_00000.parquet"

URL = f"hf://datasets/{REPO}/{FILE}"


def main():
    print("=" * 60)
    print("FINEWEB-EDU PARQUET TEST")
    print("=" * 60)

    print("Opening:")
    print(URL)
    print()

    parquet = pq.ParquetFile(URL)

    print("Parquet opened.")
    print(f"Rows: {parquet.metadata.num_rows:,}")
    print(f"Row groups: {parquet.num_row_groups:,}")
    print()

    print("Reading first row group...")

    table = parquet.read_row_group(
        0,
        columns=["text"],
    )

    texts = table["text"]

    print("Row group loaded.")
    print(f"Documents: {len(texts):,}")
    print()

    for i in range(min(5, len(texts))):
        text = texts[i].as_py()

        print(f"--- Document {i} ---")
        print(text[:300])
        print()

    print("=" * 60)
    print("FineWeb Parquet test passed.")
    print("=" * 60)


if __name__ == "__main__":
    main()