#!/usr/bin/env python3
"""
One-shot evaluator: text WER/CER, table PR/F1, drift plots, thresholds.

Defaults assume your WER layout:
  GT  text: data/WER/ground_truth/text/
  PRED text: data/WER/parsed/text/
  GT  table: data/WER/ground_truth/tables/repurchase_activity.csv
  PRED table: data/WER/parsed/tables/repurchase_activity.csv
Outputs:
  metrics JSON: data/WER/metrics/latest.json
  drift plots:  data/WER/metrics/drift/*.png

Override any path via CLI flags. Example:
  python src/evaluate_parser.py \
    --gt-text-dir data/WER/ground_truth/text \
    --pred-text-dir data/parsed/pages/Apple_SEA \
    --gt-table data/WER/ground_truth/tables/repurchase_activity.csv \
    --pred-table data/parsed/Apple_SEA/tables/repurchase_activity.csv \
    --assert-thresholds
"""

from __future__ import annotations
import argparse, json, re, csv, sys
from pathlib import Path

# -------- Default Paths -------------------------------------------------------
GT_TEXT_DIR_DEFAULT   = Path("data/WER/ground_truth/text")
PRED_TEXT_DIR_DEFAULT = Path("data/WER/parsed/text")
GT_TABLE_DEFAULT      = Path("data/WER/ground_truth/tables/repurchase_activity.csv")
PRED_TABLE_DEFAULT    = Path("data/WER/parsed/tables/repurchase_activity.csv")

METRICS_JSON_DEFAULT  = Path("data/WER/metrics/latest.json")
PLOTS_DIR_DEFAULT     = Path("data/WER/metrics/drift")

# -------- Thresholds (used only if --assert-thresholds) ----------------------
TEXT_WER_MAX_DEFAULT = 0.10   # <= 10% word error
TEXT_CER_MAX_DEFAULT = 0.10   # <= 8% char error
TABLE_F1_MIN_DEFAULT = 0.80   # >= 90% F1

# -------- Utilities ----------------------------------------------------------
def normalize_text(s: str) -> str:
    s = s.lower()
    s = s.replace("—","-").replace("–","-").replace("’","'").replace("“",'"').replace("”",'"')
    s = re.sub(r"\s+", " ", s).strip()
    return s

def load_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore")

def wer(ref: str, hyp: str) -> float:
    r, h = ref.split(), hyp.split()
    R, H = len(r), len(h)
    dp = [[0]*(H+1) for _ in range(R+1)]
    for i in range(R+1): dp[i][0] = i
    for j in range(H+1): dp[0][j] = j
    for i in range(1, R+1):
        ri = r[i-1]
        for j in range(1, H+1):
            cost = 0 if ri == h[j-1] else 1
            dp[i][j] = min(dp[i-1][j]+1, dp[i][j-1]+1, dp[i-1][j-1]+cost)
    return dp[R][H] / max(1, R)

def cer(ref: str, hyp: str) -> float:
    R, H = len(ref), len(hyp)
    dp = [[0]*(H+1) for _ in range(R+1)]
    for i in range(R+1): dp[i][0] = i
    for j in range(H+1): dp[0][j] = j
    for i in range(1, R+1):
        rc = ref[i-1]
        for j in range(1, H+1):
            cost = 0 if rc == hyp[j-1] else 1
            dp[i][j] = min(dp[i-1][j]+1, dp[i][j-1]+1, dp[i-1][j-1]+cost)
    return dp[R][H] / max(1, R)

def numeric_token_ratio(text: str) -> float:
    toks = re.findall(r"\w+|\S", text)
    if not toks: return 0.0
    nums = sum(bool(re.fullmatch(r"[+-]?\d+(\.\d+)?%?", t)) for t in toks)
    return nums / len(toks)

def norm_cell(x: str) -> str:
    x = (x or "").strip().lower()
    y = x.replace("$","").replace(",","")
    if y.endswith("%"): y = y[:-1]
    return y

def read_csv_matrix(path: Path) -> list[list[str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return [[norm_cell(c) for c in row] for row in csv.reader(f)]

def cell_prf1(gt: list[list[str]], pred: list[list[str]]):
    rows = max(len(gt), len(pred))
    cols = max(len(gt[0]) if gt else 0, len(pred[0]) if pred else 0)
    tp = fp = fn = 0
    for i in range(rows):
        for j in range(cols):
            g = gt[i][j]   if i < len(gt)   and j < len(gt[i])   else ""
            p = pred[i][j] if i < len(pred) and j < len(pred[i]) else ""
            if p == "":
                if g != "": fn += 1
            else:
                if g == p: tp += 1
                else: fp += 1
    prec = tp/(tp+fp) if (tp+fp) else 0.0
    rec  = tp/(tp+fn) if (tp+fn) else 0.0
    f1   = (2*prec*rec)/(prec+rec) if (prec+rec) else 0.0
    return prec, rec, f1, {"tp": tp, "fp": fp, "fn": fn}

# -------- Evaluations --------------------------------------------------------
def eval_text(gt_dir: Path, pred_dir: Path) -> dict:
    if not gt_dir.exists(): raise FileNotFoundError(f"Missing GT text dir: {gt_dir}")
    if not pred_dir.exists(): raise FileNotFoundError(f"Missing predicted text dir: {pred_dir}")

    pairs = []
    for gt in sorted(gt_dir.glob("*.txt")):
        cand = pred_dir / gt.name
        if not cand.exists():
            alt = pred_dir / (gt.stem + ".md")
            if alt.exists(): cand = alt
        if not cand.exists():
            print(f"[warn] skipping {gt.name}: no prediction in {pred_dir}")
            continue
        ref = normalize_text(load_text(gt))
        hyp = normalize_text(load_text(cand))
        pairs.append((gt.name, ref, hyp))

    if not pairs:
        raise RuntimeError("No GT/prediction text pairs found")

    total_w = total_c = 0.0
    details = {}
    for name, ref, hyp in pairs:
        w = wer(ref, hyp); c = cer(ref, hyp)
        total_w += w; total_c += c
        details[name] = {"wer": w, "cer": c}

    n = len(pairs)
    return {"text": {"wer_avg": total_w/n, "cer_avg": total_c/n, "files": details}}

def eval_table(gt_csv: Path, pred_csv: Path) -> dict:
    if not gt_csv.exists():  raise FileNotFoundError(f"Missing GT table: {gt_csv}")
    if not pred_csv.exists(): raise FileNotFoundError(f"Missing predicted table: {pred_csv}")
    gt, pr = read_csv_matrix(gt_csv), read_csv_matrix(pred_csv)
    prec, rec, f1, counts = cell_prf1(gt, pr)
    return {"tables": {"cell_precision": prec, "cell_recall": rec, "cell_f1": f1, "counts": counts}}

def make_drift_plots(parsed_text_dir: Path, plots_dir: Path) -> dict:
    """
    Creates histograms in plots_dir. Uses matplotlib; no seaborn; no custom colors/styles.
    """
    import matplotlib.pyplot as plt

    parsed_text_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)

    chunks, ratios = [], []
    for p in sorted(list(parsed_text_dir.glob("*.txt")) + list(parsed_text_dir.glob("*.md"))):
        s = p.read_text(encoding="utf-8", errors="ignore")
        for ch in re.split(r"\n{2,}", s):
            ch = ch.strip()
            if not ch: continue
            chunks.append(len(ch))
            ratios.append(numeric_token_ratio(ch))

    # Plot 1
    plt.figure()
    plt.hist(chunks, bins=40)
    plt.title("Chunk length distribution")
    plt.savefig(plots_dir / "chunk_lengths.png", bbox_inches="tight")

    # Plot 2
    plt.figure()
    plt.hist(ratios, bins=40)
    plt.title("Numeric token ratio distribution")
    plt.savefig(plots_dir / "numeric_token_ratio.png", bbox_inches="tight")

    return {
        "drift_summary": {
            "chunks_count": len(chunks),
            "chunk_len_mean": (sum(chunks)/len(chunks)) if chunks else 0,
            "num_ratio_mean": (sum(ratios)/len(ratios)) if ratios else 0,
        }
    }

# -------- Main ----------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="End-to-end parsing evaluation")
    ap.add_argument("--gt-text-dir",  type=Path, default=GT_TEXT_DIR_DEFAULT)
    ap.add_argument("--pred-text-dir",type=Path, default=PRED_TEXT_DIR_DEFAULT,
                    help="Directory containing predicted text files (e.g., p019.txt).")
    ap.add_argument("--gt-table",     type=Path, default=GT_TABLE_DEFAULT)
    ap.add_argument("--pred-table",   type=Path, default=PRED_TABLE_DEFAULT)
    ap.add_argument("--metrics-json", type=Path, default=METRICS_JSON_DEFAULT)
    ap.add_argument("--plots-dir",    type=Path, default=PLOTS_DIR_DEFAULT)
    ap.add_argument("--assert-thresholds", action="store_true",
                    help="Fail process if metrics violate thresholds.")
    ap.add_argument("--text-wer-max", type=float, default=TEXT_WER_MAX_DEFAULT)
    ap.add_argument("--text-cer-max", type=float, default=TEXT_CER_MAX_DEFAULT)
    ap.add_argument("--table-f1-min", type=float, default=TABLE_F1_MIN_DEFAULT)
    args = ap.parse_args()

    # evaluations
    text_metrics  = eval_text(args.gt_text_dir, args.pred_text_dir)
    table_metrics = eval_table(args.gt_table, args.pred_table)
    drift_summary = make_drift_plots(args.pred_text_dir, args.plots_dir)

    # merge + write metrics
    metrics = {}
    if args.metrics_json.exists():
        try:
            metrics = json.loads(args.metrics_json.read_text())
        except Exception:
            metrics = {}
    metrics.update(text_metrics)
    metrics.update(table_metrics)
    metrics.update(drift_summary)

    args.metrics_json.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_json.write_text(json.dumps(metrics, indent=2))
    print(json.dumps(metrics, indent=2))

    # optional assertions
    if args.assert_thresholds:
        wer_avg = metrics["text"]["wer_avg"]
        cer_avg = metrics["text"]["cer_avg"]
        f1      = metrics["tables"]["cell_f1"]
        errs = []
        if wer_avg > args.text_wer_max:
            errs.append(f"WER too high: {wer_avg:.3f} > {args.text_wer_max:.3f}")
        if cer_avg > args.text_cer_max:
            errs.append(f"CER too high: {cer_avg:.3f} > {args.text_cer_max:.3f}")
        if f1 < args.table_f1_min:
            errs.append(f"Table F1 too low: {f1:.3f} < {args.table_f1_min:.3f}")
        if errs:
            print("\nQUALITY GATES FAILED:")
            for e in errs: print(" -", e)
            sys.exit(1)

if __name__ == "__main__":
    main()
