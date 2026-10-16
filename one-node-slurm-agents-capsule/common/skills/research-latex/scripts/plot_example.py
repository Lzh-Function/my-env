#!/usr/bin/env python3
"""Regenerate the demonstration vector figure from *synthetic* CSV.
Optional dependency: matplotlib (the bundle already includes the generated PDF).
Usage: uv run --no-project --with matplotlib python plot_example.py input.csv output.pdf
"""
import argparse
import csv
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv', type=Path)
    parser.add_argument('pdf', type=Path)
    args = parser.parse_args()
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise SystemExit('matplotlib is optional but required to regenerate this figure') from exc
    with args.csv.open(encoding='utf-8', newline='') as f:
        records = list(csv.DictReader(f))
    x = [int(r['step']) for r in records]
    fig, ax = plt.subplots(figsize=(5.6, 3.0), constrained_layout=True)
    for key, label, linestyle in [('baseline', 'Baseline', '-'), ('variant_a', 'Variant A', '--'), ('variant_b', 'Variant B', '-.')]:
        ax.plot(x, [float(r[key]) for r in records], label=label, linewidth=1.9, linestyle=linestyle)
    ax.set_xlabel('Illustrative step (arbitrary unit)')
    ax.set_ylabel('Illustrative loss (a.u.)')
    ax.set_title('SYNTHETIC DATA — NOT EXPERIMENTAL', fontsize=9)
    ax.grid(alpha=0.18)
    ax.legend(frameon=False, fontsize=8)
    args.pdf.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.pdf, bbox_inches='tight')
    plt.close(fig)
    print(f'Wrote {args.pdf}')


if __name__ == '__main__':
    main()
