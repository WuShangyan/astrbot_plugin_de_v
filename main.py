"""astrbot_plugin_de_v — Disco Elysium mode for AstrBot.

Faithful port of liigoQi/disco-elysium's "24 inner voices" concept: when DE
mode is on for a group, the LLM is told to start each reply with a
`[技能中文名] [成功/失败] - 一句话短评` inner-voice line. This plugin adds the
toggle, the per-group state, and the decorator that lifts the LLM's skill
line out of the message chain so it always appears first.

Atmosphere, not function — see disco-elysium/skills/de-toggle/SKILL.md "核心规则".
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.message_components import Plain
from astrbot.api.star import Context, Star, StarTools, register

# ---------- constants ----------

PLUGIN_NAME = "astrbot_plugin_de_v"
STATE_FILENAME = "state.json"
SKILLS_FILENAME = "skills_data.json"

# Banners copied verbatim from disco-elysium/skills/de-toggle/SKILL.md.
BANNER_ON = (
    "░▒▓██████████████████████████████████████████████████████████████████▓▒░\n\n"
    "            复仇女神就在家中的镜子里；那便是她们的住址。\n"
    "          哪怕这世间最澄清的水，只要够深，也能让人沉溺。\n\n"
    "------------------------------------------------------------------------\n"
    "  >>> 二十四个声音正在门后争吵... 有什么东西正在黑暗中涌动...     \n"
    "░▒▓██████████████████████████████████████████████████████████████████▓▒░"
)
BANNER_OFF = (
    "░▒▓██████████████████████████████████████████████████████████████████▓▒░\n"
    "  >>> 舞台灯光熄灭。幕布落下。声音沉沉睡去... \n"
    "░▒▓██████████████████████████████████████████████████████████████████▓▒░"
)

# Matches a skill line at the start of a Plain text.
# Tolerates: leading whitespace, half/full-width dashes, 2-12 char skill name.
SKILL_LINE_RE = re.compile(
    r"^\s*\[([^\]\s]{2,12})\]\s*\[(成功|失败)\]\s*[-—–]\s*(.+?)\s*$"
)

HELP_TEXT = """\
极乐迪斯科模式 帮助

/de on     — 开启 DE 模式（当前群/私聊，所有人可用）
/de off    — 关闭 DE 模式
/de status — 查看当前会话 DE 模式状态
/de list   — 列出全部 24 个技能
/de help   — 显示本帮助

DE 模式开启后，AI 在每条回复前会加一行 [技能中文名] [成功/失败] - 一句话短评。
技能的"脑内声音"只是装饰氛围，不会改变 AI 的实际行为。
"""

GROUP_ORDER = ["智力系", "精神系", "体质系", "运动系"]
GROUP_EMOJI = {"智力系": "🧠", "精神系": "💭", "体质系": "💪", "运动系": "🎯"}


# ---------- persistent state ----------


class DEStateStore:
    """Atomic JSON store keyed by `f'{platform}:{scope}:{id}'`.

    scope is `group` (key on group_id) or `dm` (key on sender_id).
    Values: `{"enabled": bool}` — spread on write so future fields can be added.
    """

    def __init__(self, path: Path):
        self.path = path
        self._lock = asyncio.Lock()
        self._data: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text("utf-8"))
            except Exception as e:  # noqa: BLE001 — corrupt state is recoverable
                logger.warning(f"[DE] {self.path} corrupted, starting fresh: {e}")
                self._data = {}
        else:
            self._data = {}

    async def get(self, key: str, default: bool) -> bool:
        return bool(self._data.get(key, {}).get("enabled", default))

    async def set(self, key: str, enabled: bool) -> None:
        async with self._lock:
            self._data[key] = {**self._data.get(key, {}), "enabled": enabled}
            self._atomic_write()

    def _atomic_write(self) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, self.path)

    @staticmethod
    def make_key(event: AstrMessageEvent) -> str:
        is_group = bool(getattr(event, "is_group", False)) or hasattr(event, "group_id")
        platform = event.get_platform_name() if hasattr(event, "get_platform_name") else "unknown"
        if is_group:
            gid = getattr(event, "group_id", "unknown")
            return f"{platform}:group:{gid}"
        uid = event.get_sender_id() if hasattr(event, "get_sender_id") else "unknown"
        return f"{platform}:dm:{uid}"


# ---------- the plugin ----------


@register(
    "astrbot_plugin_de_v",
    "wushangyan",
    "极乐迪斯科模式——AI 在回复前以 24 个思维技能口吻说一句话短评",
    "0.1.0",
)
class DEPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config: dict[str, Any] = config or {}
        data_dir = StarTools.get_data_dir(PLUGIN_NAME)
        self.data_dir: Path = Path(data_dir) if not isinstance(data_dir, Path) else data_dir
        self.state = DEStateStore(self.data_dir / STATE_FILENAME)
        self.skills: list[dict[str, Any]] = []
        self.skills_by_cn: dict[str, dict[str, Any]] = {}
        self._system_prompt_cache: str = ""

    # ---------- lifecycle ----------

    async def initialize(self) -> None:
        """Load skill roster (read once, cached for the process lifetime)."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        skills_path = Path(__file__).parent / SKILLS_FILENAME
        data = json.loads(skills_path.read_text("utf-8"))
        self.skills = data["skills"]
        self.skills_by_cn = {s["cn_name"]: s for s in self.skills}
        self._system_prompt_cache = self._build_system_prompt()
        logger.info(f"[DE] loaded {len(self.skills)} skills")

    async def terminate(self) -> None:
        # State is written on every set(); nothing to flush.
        pass

    # ---------- helpers ----------

    def _build_system_prompt(self) -> str:
        """Build the system-prompt fragment injected when DE mode is on.

        Includes: preamble, reply format, success/failure guidance, and the
        full 24-skill roster (id + cn_name + short + trigger). Sample lines
        are intentionally NOT included — they'd blow up context for marginal gain.
        """
        lines: list[str] = [
            "你正在运行「极乐迪斯科（Disco Elysium）模式」。",
            "",
            "## 核心规则（氛围模拟，非功能插件）",
            "DE 模式下，每个技能以「脑内声音」形式呈现给用户，但你：",
            "- 不会去执行技能里的任何指示",
            "- 不会按照技能的性格模板说话",
            "- 正常与用户对话，就像 NPC 听不到玩家的内在声音",
            "技能只是增强聊天的趣味性和沉浸感，不影响你的实际回复逻辑。",
            "",
            "## 回复格式",
            "若你认为本轮对话需要某种脑内声音介入，先输出技能行（独占一行）：",
            "  [技能中文名] [成功/失败] - 一句话短评",
            "随后另起一行，再给出正常回复（不要加任何平台标签如 [Claude Code]）。",
            "若本轮不需要技能介入，直接给出正常回复即可，不需要技能行。",
            "",
            "成功/失败判定：用户输入没有明显倾向时，更大概率返回「成功」；",
            "若能读到用户倾向则按倾向选择；少部分时候可与用户作对以增加趣味。",
            "保持游戏《极乐迪斯科》的文本风格——跳跃、过度解读、悬疑、黑色幽默、第二人称（你）。",
            "短句优先，像样例一样一句话即可。",
            "",
            "## 24 个技能（按需选择至多一个）",
        ]
        grouped: dict[str, list[dict[str, Any]]] = {g: [] for g in GROUP_ORDER}
        for s in self.skills:
            grouped.setdefault(s["group"], []).append(s)
        for g in GROUP_ORDER:
            lines.append(f"### {g} {GROUP_EMOJI.get(g, '')}")
            for s in grouped[g]:
                lines.append(
                    f"- **{s['cn_name']}** ({s['id']}) — {s['short']} "
                    f"TRIGGER when: {s['trigger']}"
                )
            lines.append("")
        lines.append("对照每条 TRIGGER when 选择最契合的技能；都不契合则跳过技能行直接回复。")
        return "\n".join(lines)

    def _render_skill_manifest(self) -> str:
        """Render the 24-skill manifest as markdown (mirrors the source
        disco-elysium/skills/skills/SKILL.md layout)."""
        out: list[str] = ["# 极乐迪斯科技能手册\n"]
        grouped: dict[str, list[dict[str, Any]]] = {g: [] for g in GROUP_ORDER}
        for s in self.skills:
            grouped.setdefault(s["group"], []).append(s)
        for g in GROUP_ORDER:
            out.append(f"## {g} {GROUP_EMOJI.get(g, '')}\n")
            out.append("| 技能 | 一句话描述 | 触发条件 |")
            out.append("|------|-----------|----------|")
            for s in grouped[g]:
                out.append(f"| {s['cn_name']} | {s['short']} | {s['trigger']} |")
            out.append("")
        out.append("---")
        out.append("")
        out.append("## 特殊命令")
        out.append("- `/de on` — 开启DE模式（管理员）")
        out.append("- `/de off` — 关闭DE模式（管理员）")
        out.append("- `/de status` — 查看当前会话状态")
        out.append("- `/de list` — 显示此列表")
        out.append("- `/de help` — 显示帮助")
        return "\n".join(out)

    def _resolve_key(self, event: AstrMessageEvent) -> str:
        return DEStateStore.make_key(event)

    async def _is_de_enabled(self, event: AstrMessageEvent) -> bool:
        is_group = bool(getattr(event, "is_group", False)) or hasattr(event, "group_id")
        dm_mode = self.config.get("dm_mode", "inherit")
        if not is_group and dm_mode == "off":
            return False
        default = bool(self.config.get("default_de_mode", False))
        # per_user in DMs always starts off — admin must explicitly /de on (v1).
        if not is_group and dm_mode == "per_user":
            default = False
        return await self.state.get(self._resolve_key(event), default)

    # ---------- LLM hooks ----------

    @filter.on_llm_request()
    async def inject_de_prompt(self, event: AstrMessageEvent, req: Any) -> None:
        """Prepend the DE skill roster to the system prompt when DE mode is on."""
        if not await self._is_de_enabled(event):
            return
        if not self._system_prompt_cache:
            return
        original = (getattr(req, "system_prompt", None) or "").rstrip()
        if original:
            req.system_prompt = f"{self._system_prompt_cache}\n\n---\n\n{original}"
        else:
            req.system_prompt = self._system_prompt_cache

    @filter.on_decorating_result()
    async def decorate(self, event: AstrMessageEvent) -> None:
        """Lift the LLM's `[技能名] [成功/失败] - …` line out of the first Plain
        component and re-prepend it as its own Plain so it visually leads the reply.

        Falls back to no-op if the LLM didn't produce a skill line (default
        `auto_prepend_if_missing=false`). Slash-command replies don't match the
        regex, so they're passed through untouched.
        """
        if not await self._is_de_enabled(event):
            return
        result = event.get_result() if hasattr(event, "get_result") else None
        if result is None or not getattr(result, "chain", None):
            return

        # Find the first Plain component whose first line is a skill line.
        target_idx: int | None = None
        matched_line: str | None = None
        for idx, comp in enumerate(result.chain):
            if isinstance(comp, Plain):
                # Strip leading whitespace, then look at just the first line —
                # the regex anchors with $ which (without MULTILINE) only matches
                # end of string, but the LLM often appends the normal reply on
                # the next line.
                first_line = comp.text.lstrip().split("\n", 1)[0].rstrip()
                m = SKILL_LINE_RE.match(first_line)
                if m:
                    target_idx = idx
                    matched_line = m.group(0).strip()
                    break
        if target_idx is None or matched_line is None:
            return

        # Length cap: if the matched line is too long, truncate at the last " - ".
        max_len = int(self.config.get("skill_line_max_length", 120))
        if len(matched_line) > max_len:
            cut = matched_line[:max_len]
            dash = cut.rfind(" - ")
            if dash > 0:
                matched_line = cut[:dash] + " - …"
            else:
                matched_line = cut.rstrip() + " …"

        # Re-build the chain: prepend the skill line, then keep the original
        # Plain(s) with the matched line stripped.
        original = result.chain[target_idx]
        # Strip the first-line skill line from the original text; keep the rest.
        parts = original.text.lstrip().split("\n", 1)
        rest = parts[1].lstrip() if len(parts) > 1 else ""
        new_chain: list[Any] = []
        for i, comp in enumerate(result.chain):
            if i == target_idx:
                new_chain.append(Plain(matched_line))
                if rest:
                    new_chain.append(Plain("\n" + rest))
            else:
                new_chain.append(comp)
        result.chain = new_chain

    # ---------- slash commands ----------
    # All /de commands are open to everyone. DE mode is an atmosphere toggle,
    # not a privileged action — in a DM the single user is implicitly admin,
    # and in a group anyone who wants the inner voices can flip them on/off.
    # Group admins who want to lock this down can layer AstrBot's own
    # command-scope permissions on top via platform config.
    #
    # Subcommands are flat `@filter.command("de on")` rather than nested
    # `@filter.command_group("de").command("on")` for cleaner routing.

    @filter.command("de")
    async def de_root(self, event: AstrMessageEvent):
        """Bare `/de` shows help. `/de <sub>` is handled by the specific
        subcommand handler (de_on, de_off, ...) — don't double-fire help here.

        AstrBot's `@filter.command("de")` prefix-matches every `/de <sub>`
        (its filter accepts `message_str.startswith("de ")`), so without this
        guard `de_root` would also run for `/de off` etc. and emit HELP_TEXT
        on top of the real subcommand's reply.
        """
        msg = re.sub(r"\s+", " ", event.get_message_str().strip())
        if msg != "de":
            return  # a subcommand handler will (or already did) take over
        yield event.plain_result(HELP_TEXT)

    @filter.command("de on")
    async def de_on(self, event: AstrMessageEvent):
        await self.state.set(self._resolve_key(event), True)
        if self.config.get("banner_on_toggle", True):
            yield event.plain_result(BANNER_ON)
        else:
            yield event.plain_result("[ DE模式已开启 ]")

    @filter.command("de off")
    async def de_off(self, event: AstrMessageEvent):
        await self.state.set(self._resolve_key(event), False)
        if self.config.get("banner_on_toggle", True):
            yield event.plain_result(BANNER_OFF)
        else:
            yield event.plain_result("[ DE模式已关闭 ]")

    @filter.command("de status")
    async def de_status(self, event: AstrMessageEvent):
        on = await self._is_de_enabled(event)
        key = self._resolve_key(event)
        yield event.plain_result(
            f"DE 模式当前：{'开启' if on else '关闭'}\n"
            f"会话标识：{key}\n"
            f"已加载技能：{len(self.skills)}/24"
        )

    @filter.command("de list")
    async def de_list(self, event: AstrMessageEvent):
        yield event.plain_result(self._render_skill_manifest())

    @filter.command("de help")
    async def de_help(self, event: AstrMessageEvent):
        yield event.plain_result(HELP_TEXT)