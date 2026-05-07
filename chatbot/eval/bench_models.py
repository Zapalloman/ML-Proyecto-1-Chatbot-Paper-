"""Phase 0 F0.3 — bench candidate local LLMs against the 5 standard prompts.

Runs each prompt through each model via Ollama's `/api/generate` endpoint,
captures latency-to-first-token and total tokens/sec, and writes a markdown
report to `eval/model_selection.md`.

Requires:
  - Ollama running on localhost:11434
  - Models pulled: gemma3:4b, qwen2.5:3b, gemma3:1b
  - GPU driver functional (re-run after reboot if NVML mismatch)

Usage:
  python -m eval.bench_models                   # all 3 candidates
  python -m eval.bench_models --models gemma3:4b qwen2.5:3b
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import platform
import subprocess
import time
from pathlib import Path
from typing import Iterator

import requests

OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODELS = ["gemma3:4b", "qwen2.5:3b", "gemma3:1b"]

PROMPTS: list[tuple[str, str, str]] = [
    (
        "P1",
        "EN factual",
        "Pikachu evolves into Raichu using a Thunder Stone. In one sentence, what type is Raichu?",
    ),
    (
        "P2",
        "ES factual",
        "Charizard tiene dos tipos. ¿Cuáles son? Responde en español en una frase.",
    ),
    (
        "P3",
        "EN comparative",
        "Between Mewtwo and Mew, which has higher base Special Attack? State the value.",
    ),
    (
        "P4",
        "EN lore",
        "Why is Cubone said to wear a skull on its head, according to Pokédex lore?",
    ),
    (
        "P5",
        "ES instruction-following",
        "Reply in Spanish: list three Eeveelutions and their types as 'Name: Type'.",
    ),
]


def _gpu_info() -> str:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
            text=True,
            stderr=subprocess.STDOUT,
            timeout=5,
        ).strip()
        return out
    except Exception as exc:
        return f"unavailable ({exc.__class__.__name__})"


def _ollama_version() -> str:
    try:
        return requests.get(f"{OLLAMA_URL}/api/version", timeout=5).json().get("version", "?")
    except Exception:
        return "?"


def stream_generate(model: str, prompt: str) -> Iterator[dict]:
    """Stream JSONL chunks from /api/generate."""
    payload = {"model": model, "prompt": prompt, "stream": True}
    with requests.post(f"{OLLAMA_URL}/api/generate", json=payload, stream=True, timeout=180) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            yield json.loads(line)


def bench_one(model: str, prompt_id: str, prompt: str) -> dict:
    print(f"  [{prompt_id}] running on {model} ...", flush=True)
    t_start = time.monotonic()
    t_first = None
    pieces: list[str] = []
    eval_count = 0
    eval_duration_ns = 0
    try:
        for chunk in stream_generate(model, prompt):
            if t_first is None:
                t_first = time.monotonic()
            if "response" in chunk:
                pieces.append(chunk["response"])
            if chunk.get("done"):
                eval_count = chunk.get("eval_count", 0)
                eval_duration_ns = chunk.get("eval_duration", 0)
        ok = True
        err = None
    except Exception as exc:
        ok = False
        err = f"{exc.__class__.__name__}: {exc}"
    t_end = time.monotonic()

    answer = "".join(pieces).strip()
    ttfb = (t_first - t_start) if t_first else None
    total = t_end - t_start
    tps = (eval_count / (eval_duration_ns / 1e9)) if eval_duration_ns else None

    return {
        "model": model,
        "prompt_id": prompt_id,
        "prompt": prompt,
        "answer": answer,
        "time_to_first_token_s": ttfb,
        "total_s": total,
        "eval_tokens": eval_count,
        "tokens_per_s": tps,
        "ok": ok,
        "error": err,
    }


def write_report(results: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    by_model: dict[str, list[dict]] = {}
    for r in results:
        by_model.setdefault(r["model"], []).append(r)

    lines: list[str] = []
    lines.append("# Model selection — Phase 0 F0.3\n")
    lines.append(f"**Date**: {_dt.datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"**Platform**: {platform.platform()}")
    lines.append(f"**GPU**: {_gpu_info()}")
    lines.append(f"**Ollama**: {_ollama_version()}")
    lines.append("")
    lines.append("## Summary table\n")
    lines.append("| Model | TTFT (s) median | Tok/s median | OK count |")
    lines.append("|---|---|---|---|")
    for model, rows in by_model.items():
        ttfts = [r["time_to_first_token_s"] for r in rows if r["time_to_first_token_s"] is not None]
        tpss = [r["tokens_per_s"] for r in rows if r["tokens_per_s"] is not None]
        ok_count = sum(1 for r in rows if r["ok"])
        ttft_med = sorted(ttfts)[len(ttfts) // 2] if ttfts else None
        tps_med = sorted(tpss)[len(tpss) // 2] if tpss else None
        ttft_s = f"{ttft_med:.2f}" if ttft_med is not None else "n/a"
        tps_s = f"{tps_med:.1f}" if tps_med is not None else "n/a"
        lines.append(f"| `{model}` | {ttft_s} | {tps_s} | {ok_count}/{len(rows)} |")
    lines.append("")
    lines.append("## Detailed results\n")
    for model, rows in by_model.items():
        lines.append(f"### `{model}`\n")
        for r in rows:
            ttft = f"{r['time_to_first_token_s']:.2f}s" if r["time_to_first_token_s"] is not None else "—"
            tps = f"{r['tokens_per_s']:.1f}" if r["tokens_per_s"] is not None else "—"
            lines.append(f"**{r['prompt_id']}** ({r['prompt']!r})  ")
            lines.append(f"_TTFT: {ttft} · {tps} tok/s · {r['eval_tokens']} tokens · ok={r['ok']}_  ")
            if r["ok"]:
                lines.append("```")
                lines.append(r["answer"])
                lines.append("```")
            else:
                lines.append(f"**ERROR**: {r['error']}")
            lines.append("")
    lines.append("---\n")
    lines.append("## Verdict\n")
    lines.append("**Selected**: _<fill in after reviewing answers above against the rubric in MODEL-SELECTION.md>_  ")
    lines.append("**Rationale**: _<fill in>_  ")
    lines.append("**Known weak points to carry into the test report**: _<fill in>_  ")

    output_path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    p.add_argument("--output", type=Path, default=Path("eval/model_selection.md"))
    args = p.parse_args(argv)

    print(f"GPU: {_gpu_info()}")
    print(f"Ollama: {_ollama_version()}\n")

    results: list[dict] = []
    for model in args.models:
        print(f"== {model} ==")
        for pid, label, prompt in PROMPTS:
            r = bench_one(model, pid, prompt)
            print(f"    -> {len(r['answer'])} chars · ttft={r['time_to_first_token_s']} · tps={r['tokens_per_s']}")
            results.append(r)

    write_report(results, args.output)
    print(f"\nWrote {args.output} ({len(results)} runs).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
