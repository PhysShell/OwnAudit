"""The executive report (Russian) — the audience-B counterpart of the dashboard.

Turns the heap-collector artifact (runtime.json: confirmed retention with owners) and
the health report's pain table into a short human document: what leaks, who holds it,
what to do — without the 72k raw findings. Fix advice comes from rules_own.json, the
same catalog the dashboard and the annotator use.

    python3 -m report.exec_cli --runtime artifacts/runtime-sts.json \
        --health artifacts/health-report.md --out artifacts/exec-report.md \
        [--title "..."]
"""
from __future__ import annotations

import argparse
import json
import re

from report.rules_map import load_rules_map

_KIND_RU = {
    "static-event": "статическое событие",
    "timer": "таймер (TimerQueue)",
    "static-field": "статическое поле",
    "other": "прочий корень",
}

# which own-rule explains a root kind — the fix advice source
_KIND_RULE = {"static-event": "OWN001", "timer": "OWN-TIMER", "static-field": "OWN014"}


def _pain_rows(health_path: str, limit: int = 6) -> list:
    """First markdown table after the pain heading, whatever the generator called it."""
    with open(health_path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    rows, in_section, seen_rule_row = [], False, False
    for line in lines:
        if line.startswith("## "):
            in_section = "hurts" in line.lower() or "module pain" in line.lower()
            seen_rule_row = False
            continue
        if not in_section or not line.startswith("|"):
            continue
        if set(line.replace("|", "").replace(":", "").strip()) <= {"-"}:
            seen_rule_row = True
            continue
        if seen_rule_row:
            cells = [c.strip().strip("`") for c in line.strip("|").split("|")]
            if len(cells) >= 5:
                rows.append(cells)
    return rows[:limit]


def build(runtime_path: str, health_path: str, out_path: str,
          title: str = "STS — сводка аудита памяти") -> None:
    with open(runtime_path, encoding="utf-8") as fh:
        runtime = json.load(fh)
    retained = [r for r in runtime.get("retained", []) if r.get("count")]
    heap = runtime.get("heapStats") or {}
    catalog = load_rules_map()

    kind_rank = {"static-event": 0, "timer": 1, "static-field": 2}

    def best_root(rec):
        roots = rec.get("roots") or []
        return min(roots, key=lambda r: kind_rank.get(r.get("kind"), 9)) if roots else {}

    # the most PROVEN retention first: an event/timer root names a real product owner,
    # a bare static list may be the measuring scenario's own bookkeeping.
    retained.sort(key=lambda r: (kind_rank.get(best_root(r).get("kind"), 9), -r["count"]))

    total_instances = sum(r["count"] for r in retained)
    out = ["# %s" % title, ""]
    out += ["**Главное:** куча подтверждает утечку по **%d** типам — суммарно **%d** экземпляров, "
            "которые обязаны были собраться сборщиком мусора, но удерживаются живыми."
            % (len(retained), total_instances)]
    if heap.get("bytes"):
        out += ["", "Проверка честности: из %.0f МБ кучи %.0f МБ (%.1f%%) реально достижимы от GC-корней — "
                "это удержание, а не «ленивый GC»."
                % (heap["bytes"] / 1048576.0, heap.get("reachableBytes", 0) / 1048576.0,
                   100.0 * heap.get("reachableBytes", 0) / heap["bytes"])]
    scenario = runtime.get("scenario")
    if scenario:
        out += ["", "Сценарий: _%s_%s." % (scenario,
                (" (%d итераций)" % runtime["iterations"]) if runtime.get("iterations") else "")]

    out += ["", "## Подтверждённые утечки — кто держит объекты", "",
            "| Тип | Экземпляров | Чем удержан | Владелец |", "|---|---:|---|---|"]
    advice_rules = []
    for rec in retained:
        root = best_root(rec)
        kind = root.get("kind") or "other"
        holder = (root.get("holder") or "?") + (("." + root["member"]) if root.get("member") else "")
        generic_holder = holder.startswith("System.Collections.")
        out.append("| `%s` | %d | %s | `%s`%s |"
                   % (rec["type"], rec["count"], _KIND_RU.get(kind, kind), holder,
                      " ¹" if generic_holder else ""))
        rule = _KIND_RULE.get(kind)
        if rule and rule not in advice_rules:
            advice_rules.append(rule)

    out += ["", "¹ Держатель — обобщённый список: возможно, внутренняя структура сценария измерения, "
            "а не продуктовый код; уточняется расширенной выборкой цепочек (`--max-chains`).", ""]
    out += ["", "## Почему это течёт и как чинить", ""]
    for rule in advice_rules:
        d = catalog.get(rule, {})
        out += ["**%s — %s.** %s" % (rule, d.get("title_ru", rule), d.get("why_ru", "")),
                "", "_Как чинить:_ %s" % d.get("fix_ru", ""), ""]

    pain = _pain_rows(health_path)
    if pain:
        out += ["## Где болит в коде (по статическому аудиту)", "",
                "| Модуль | Индекс боли | Находок | Топ-категория |", "|---|---:|---:|---|"]
        for cells in pain:
            out.append("| `%s` | %s | %s | %s |" % (cells[0], cells[1], cells[2], cells[-1]))
        out += [""]

    out += ["## Следующие шаги", "",
            "1. Чинить подтверждённые утечки из таблицы выше — это не гипотезы, их держит куча.",
            "2. Пройти сценарием остальные экраны: находки без runtime-подтверждения — кандидаты,",
            "   их подтверждает или закрывает следующий прогон коллектора.",
            "3. После фиксов повторить прогон: отчёт должен показать спад удержанных экземпляров",
            "   (baseline-гейт в CI не даст долгу вернуться).", ""]

    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))
    print("executive report written to %s" % out_path)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the Russian executive audit report.")
    ap.add_argument("--runtime", required=True, help="runtime.json from `own-audit collect`")
    ap.add_argument("--health", required=True, help="health-report.md (pain table source)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default="STS — сводка аудита памяти")
    args = ap.parse_args(argv)
    build(args.runtime, args.health, args.out, args.title)


if __name__ == "__main__":
    main()
