"""Fine-tune RF-DETR to detect weapons (guns, knives, ...) - the ONLY way to get real gun detection.

The generic COCO model has no "gun" class and only a weak "knife" class. A model trained on
weapon images fixes that. Training on a CPU laptop is impractical (days) - run this on a free
GPU such as Google Colab / Kaggle, then copy the resulting .pth file back to this machine.

1. Get a weapon dataset in COCO format with this layout (a Roboflow "COCO" export has it):
       my_dataset/
         train/  _annotations.coco.json + images
         valid/  _annotations.coco.json + images
         test/   _annotations.coco.json + images   (optional)
   CHECK THE DATASET LICENCE before using it commercially.
2. On the GPU machine:   pip install rfdetr
                         python train_weapon_model.py --dataset my_dataset --size nano --epochs 40
3. Copy the best checkpoint (printed at the end, usually output/checkpoint_best_total.pth) to
   backend/models/weapon.pth  and set in backend/.env:
       WEAPON_MODEL_PATH=models/weapon.pth
       WEAPON_MODEL_SIZE=nano            # same value as --size
       WEAPON_CLASS_NAMES=gun,knife      # same order as the dataset's categories (only needed if the file lacks names)
4. Restart the server. The Live tile will say "custom weapon model" next to Weapons.

Use your own CCTV-style footage in the training set where you can: weapons seen from above, far
away and partly hidden look very different from the clean photos most datasets contain.
"""
from __future__ import annotations

import argparse


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", required=True, help="dataset folder (COCO layout, see above)")
    ap.add_argument("--size", default="nano", choices=["nano", "small", "medium", "large", "base"])
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--out", default="output")
    args = ap.parse_args()

    import rfdetr

    cls = {"nano": "RFDETRNano", "small": "RFDETRSmall", "medium": "RFDETRMedium", "large": "RFDETRLarge", "base": "RFDETRBase"}[args.size]
    model = getattr(rfdetr, cls)()
    model.train(
        dataset_dir=args.dataset,
        epochs=args.epochs,
        batch_size=args.batch,
        grad_accum_steps=max(1, 16 // args.batch),
        lr=args.lr,
        output_dir=args.out,
    )
    print(f"\nTraining finished. Look in '{args.out}' for checkpoint_best_total.pth (or the newest .pth file).")


if __name__ == "__main__":
    main()
