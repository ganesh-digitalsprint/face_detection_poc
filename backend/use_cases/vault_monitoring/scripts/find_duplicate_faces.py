"""Read-only report of near-duplicate employee face enrollments in Qdrant."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from qdrant_client import models

# Allow direct execution as `python scripts/find_duplicate_faces.py`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.ml_config import load_ml_config_file
from app.ml.model_config import get_face_model_config
from app.services.qdrant_service import get_qdrant_service


def scan(threshold: float) -> list[dict[str, object]]:
    service = get_qdrant_service()
    client = service.client
    model_name = get_face_model_config().model_name
    employee_ids: set[str] = set()
    offset = None
    while True:
        records, offset = client.scroll(
            collection_name=service.collection_name,
            scroll_filter=models.Filter(
                must=[models.FieldCondition(key="model_name", match=models.MatchValue(value=model_name))],
                must_not=[models.IsEmptyCondition(is_empty=models.PayloadField(key="employee_id"))],
            ),
            limit=512,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for record in records:
            payload = record.payload or {}
            employee_id = payload.get("employee_id")
            if employee_id is not None:
                employee_ids.add(str(employee_id))
        if offset is None:
            break

    ids = sorted(employee_ids)
    pairs: list[dict[str, object]] = []
    chunk_size = 128

    def vector_blocks(employee_id: str):
        point_offset = None
        while True:
            records, point_offset = client.scroll(
                collection_name=service.collection_name,
                scroll_filter=models.Filter(must=[
                    models.FieldCondition(key="model_name", match=models.MatchValue(value=model_name)),
                    models.FieldCondition(key="employee_id", match=models.MatchValue(value=employee_id)),
                ]),
                limit=chunk_size,
                offset=point_offset,
                with_payload=True,
                with_vectors=True,
            )
            vectors = []
            for record in records:
                raw = record.vector
                if isinstance(raw, dict):
                    raw = raw.get("")
                if raw is None or (record.payload or {}).get("employee_id") is None:
                    continue
                vector = np.asarray(raw, dtype=np.float32)
                norm = float(np.linalg.norm(vector))
                if vector.ndim == 1 and norm and np.isfinite(vector).all():
                    vectors.append(vector / norm)
            if vectors:
                yield np.stack(vectors)
            if point_offset is None:
                break

    for index, employee_a in enumerate(ids):
        for employee_b in ids[index + 1:]:
            best_distance = 2.0
            close_count = 0
            for block_a in vector_blocks(employee_a):
                for block_b in vector_blocks(employee_b):
                    distances = np.clip(1.0 - block_a @ block_b.T, 0.0, 2.0)
                    best_distance = min(best_distance, float(distances.min()))
                    close_count += int(np.count_nonzero(distances <= threshold))
            if close_count:
                pairs.append({"employee_a": employee_a, "employee_b": employee_b,
                              "best_distance": best_distance, "close_point_pairs": close_count})
    return pairs


def main() -> None:
    config = load_ml_config_file().vault_access.enrollment
    threshold = config.duplicate_distance_threshold
    if threshold is None:
        threshold = get_face_model_config().threshold
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threshold", type=float, default=threshold,
                        help=f"cosine distance threshold (default: {threshold:g})")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args()
    pairs = scan(args.threshold)
    if args.json:
        print(json.dumps(pairs, indent=2))
        return
    if not pairs:
        print(f"No cross-employee pairs at cosine distance <= {args.threshold:g}.")
        return
    headers = ("Employee A", "Employee B", "Best distance", "Close point pairs")
    rows = [(str(pair["employee_a"]), str(pair["employee_b"]),
             f"{pair['best_distance']:.6f}", str(pair["close_point_pairs"])) for pair in pairs]
    widths = [max(len(headers[i]), *(len(row[i]) for row in rows)) for i in range(4)]
    print(" | ".join(headers[i].ljust(widths[i]) for i in range(4)))
    print("-+-".join("-" * width for width in widths))
    for row in rows:
        print(" | ".join(row[i].ljust(widths[i]) for i in range(4)))


if __name__ == "__main__":
    main()
