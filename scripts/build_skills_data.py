#!/usr/bin/env python3
"""Build skills_data.json from the disco-elysium source repo.

Run from the astrbot_plugin_de_v/ root:

    python3 scripts/build_skills_data.py /path/to/disco-elysium/skills

If no argument is given, defaults to ../disco-elysium/skills (sibling project).
This script is intended for author-time use only — it is NOT shipped inside the
AstrBot plugin directory.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# System-skill directories in disco-elysium/skills/ — skip these.
SKIP_DIRS = {"de-toggle", "skills"}

# Regex patterns, kept in one place so the parser is easy to audit.
RE_FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
RE_DESC_LINE = re.compile(r"^description:\s*(.+?)\s*$", re.MULTILINE)
RE_TRIGGER = re.compile(r"TRIGGER when:\s*(.+?)\s*$")
RE_HEADING = re.compile(r"^#\s*(\S+)\s*\[([^\]]+)\]", re.MULTILINE)
RE_FIT = re.compile(r"^适合：(.+?)$", re.MULTILINE)
RE_CORE_START = re.compile(r"\*\*核心能力\*\*：\s*\n", re.MULTILINE)
RE_CORE_END = re.compile(r"\n##|\n回复样例", re.DOTALL)
RE_SAMPLE = re.compile(
    r"^-\s*\[([^\]]+)\]\s*\[(成功|失败)\]\s*[-—–]\s*(.+?)\s*$",
    re.MULTILINE,
)


def parse_skill_md(skill_md: Path) -> dict:
    """Parse one SKILL.md into the structured dict expected by skills_data.json."""
    text = skill_md.read_text(encoding="utf-8")

    fm_match = RE_FRONTMATTER.match(text)
    if not fm_match:
        raise ValueError(f"{skill_md}: no YAML frontmatter")
    fm_body = fm_match.group(1)
    body = text[fm_match.end():]

    # Frontmatter: id from filename, description + trigger from the description: line.
    skill_id = skill_md.parent.name
    desc_match = RE_DESC_LINE.search(fm_body)
    if not desc_match:
        raise ValueError(f"{skill_md}: no description: line in frontmatter")
    description = desc_match.group(1).strip()
    trigger_match = RE_TRIGGER.search(description)
    if not trigger_match:
        raise ValueError(f"{skill_md}: no TRIGGER when: clause in description")
    trigger = trigger_match.group(1).strip()

    # Body: cn_name + group from the "# 中文名 [组系]" heading.
    heading_match = RE_HEADING.search(body)
    if not heading_match:
        raise ValueError(f"{skill_md}: no '# 中文名 [组系]' heading")
    cn_name = heading_match.group(1).strip()
    group = heading_match.group(2).strip()

    # 适合：
    fit_match = RE_FIT.search(body)
    fit = fit_match.group(1).strip() if fit_match else ""

    # **核心能力** paragraph (greedy until the next ## section or 回复样例:).
    core_match = RE_CORE_START.search(body)
    if not core_match:
        raise ValueError(f"{skill_md}: no **核心能力**： paragraph")
    rest_after = body[core_match.end():]
    core_end = RE_CORE_END.search(rest_after)
    core = (rest_after[: core_end.start()] if core_end else rest_after).strip()

    # Short = first sentence of core (split on the first 。).
    short = core.split("。")[0].strip() + "。"

    # Sample lines — count varies per skill (most are 5, volition has 6, etc.).
    # We just require at least one success and one failure to mirror the source contract.
    samples = [
        {"tag": m.group(2), "text": m.group(3).strip()}
        for m in RE_SAMPLE.finditer(body)
    ]
    if not samples:
        raise ValueError(f"{skill_md}: no sample lines parsed")
    tag_counts = {t: sum(1 for s in samples if s["tag"] == t) for t in ("成功", "失败")}
    if tag_counts["成功"] < 1 or tag_counts["失败"] < 1:
        raise ValueError(
            f"{skill_md}: need at least 1 success + 1 failure sample, got {tag_counts}"
        )

    return {
        "id": skill_id,
        "cn_name": cn_name,
        "group": group,
        "short": short,
        "trigger": trigger,
        "fit": fit,
        "core": core,
        "format_bullet": f"- 回复格式：[{cn_name}] [成功/失败] - 回复内容",
        "samples": samples,
    }


def group_order_key(skill: dict) -> tuple[int, str]:
    """Sort skills by group order then cn_name for stable output."""
    order = {"智力系": 0, "精神系": 1, "体质系": 2, "运动系": 3}
    return (order.get(skill["group"], 99), skill["cn_name"])


def main(src: str) -> None:
    src_path = Path(src)
    if not src_path.is_dir():
        sys.exit(f"Source directory not found: {src_path}")

    skill_dirs = sorted(
        d for d in src_path.iterdir() if d.is_dir() and d.name not in SKIP_DIRS
    )
    if len(skill_dirs) != 24:
        sys.exit(
            f"Expected 24 inner skills under {src_path}, found {len(skill_dirs)}: "
            f"{[d.name for d in skill_dirs]}"
        )

    skills = []
    for d in skill_dirs:
        md = d / "SKILL.md"
        if not md.exists():
            sys.exit(f"{md}: SKILL.md not found")
        skills.append(parse_skill_md(md))
    skills.sort(key=group_order_key)

    out = {"version": 1, "skills": skills}
    out_path = Path("skills_data.json")
    out_path.write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # Print a one-line summary so the author can eyeball the output.
    by_group: dict[str, int] = {}
    for s in skills:
        by_group[s["group"]] = by_group.get(s["group"], 0) + 1
    print(
        f"Wrote {out_path} with {len(skills)} skills: "
        + ", ".join(f"{g}={n}" for g, n in sorted(by_group.items()))
    )


if __name__ == "__main__":
    default_src = (
        Path(__file__).resolve().parent.parent.parent / "disco-elysium" / "skills"
    )
    main(sys.argv[1] if len(sys.argv) > 1 else str(default_src))