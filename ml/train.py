"""手動実行用のエントリポイント。

botやCIから自動的に呼ばれることは想定していない。実施後アンケートのデータが
十分に溜まった際に、モデルが学習できる状態になっているかを手元で確認する用途。

実行例: python train.py
"""

import logging

import model

logging.basicConfig(level=logging.INFO)


def main():
    trained_model = model.train_correction_model()
    if trained_model is None:
        print("学習データが不足しているため、モデルは学習されませんでした。")
        return

    print(f"モデルを学習しました（学習データ{model.MIN_TRAINING_SAMPLES}件以上）。")


if __name__ == "__main__":
    main()
