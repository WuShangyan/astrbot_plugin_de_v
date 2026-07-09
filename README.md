# astrbot_plugin_de_v

Disco Elysium (极乐迪斯科) 模式 for [AstrBot](https://github.com/AstrBotDevs/AstrBot)——把游戏里 24 个"思维技能"的内脑独白装饰到 AI 的每条回复前。

> 忠实移植自 [liigoQi/disco-elysium](https://github.com/liigoQi/disco-elysium) Claude Code 插件,氛围模拟而非功能接管。

## 它做什么

群管理员 `/de on` 后,该群后续每条 LLM 回复前都会多出一行:

```
[逻辑思维] [成功] - 这一定就是那台把你从湮灭中撕裂的地狱机器——库普瑞斯锐影汽车。

[正常 AI 回复内容...]
```

技能由 LLM 根据 24 个技能的 `TRIGGER when:` 条件自行挑选,本插件不接管 AI 人格,只装饰回复首行。

## 安装

把整个 `astrbot_plugin_de_v/` 目录拷到 AstrBot 的插件目录:

```bash
cp -r astrbot_plugin_de_v <AstrBot>/data/plugins/
```

重启 AstrBot,插件会自动加载。

## 命令

| 命令 | 权限 | 作用 |
|------|------|------|
| `/de on` | 管理员 | 开启当前群/私聊的 DE 模式 |
| `/de off` | 管理员 | 关闭 DE 模式 |
| `/de status` | — | 查看当前会话状态 + 会话 key + 已加载技能数 |
| `/de list` | — | 列出全部 24 个技能 |
| `/de help` | — | 显示帮助 |

## 配置(`_conf_schema.json`)

通过 AstrBot 控制台 → 插件配置:

| 旋钮 | 默认 | 说明 |
|------|------|------|
| `default_de_mode` | `false` | 未记录过的群/私聊默认是否开启 DE |
| `skill_line_max_length` | `120` | 技能行最大字符数,超出截断 |
| `auto_prepend_if_missing` | `false` | LLM 漏写技能行时是否补全(v1 暂为 no-op) |
| `banner_on_toggle` | `true` | `/de on/off` 是否打印迪斯科横幅 |
| `dm_mode` | `"inherit"` | 私聊行为:`off` / `inherit`(跟 default) / `per_user` |

## 状态持久化

- 路径:`<AstrBot data>/data/plugins/astrbot_plugin_de_v/state.json`
- Key 格式:`{platform}:{scope}:{id}`,`scope ∈ {group, dm}`
- 原子写(`os.replace`),`asyncio.Lock` 守并发

## 24 个技能

| 系 | 技能 |
|----|------|
| 智力系 🧠 | 逻辑思维、博学多闻、能说会道、故弄玄虚、标新立异、见微知著 |
| 精神系 💭 | 平心定气、内陆帝国、通情达理、争强好胜、同舟共济、循循善诱 |
| 体质系 💪 | 钢筋铁骨、坚忍不拔、强身健体、食髓知味、天人感应、疑神疑鬼 |
| 运动系 🎯 | 眼明手巧、五感发达、反应速度、鬼祟玲珑、能工巧匠、从容自若 |

## 作者脚本(可选)

`scripts/build_skills_data.py` 用于作者迭代时从上游 disco-elysium 仓库重新生成 `skills_data.json`:

```bash
python3 scripts/build_skills_data.py /path/to/disco-elysium/skills
```

默认路径是相邻的 `../disco-elysium/skills`。脚本**不**进入 AstrBot 插件目录,仅作者本地使用。

## 文件结构

```
astrbot_plugin_de_v/
├── metadata.yaml                # AstrBot 插件清单 (6 字段)
├── _conf_schema.json            # 5 旋钮用户配置 schema
├── main.py                      # DEPlugin 类 + 装饰器 + 状态机
├── skills_data.json             # 24 技能数据 (build 脚本生成)
├── README.md                    # 本文件
└── scripts/
    └── build_skills_data.py     # 作者时一次性转换脚本
```

## 许可

MIT(若与上游不一致,以 `LICENSE` 为准)。