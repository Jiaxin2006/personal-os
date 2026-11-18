# MVP 模块分工与接口 v1

开发路线：SwiftUI 原生窗口和菜单栏；Python 标准库业务层；SQLite；通过本地子进程 JSON stdin/stdout 调用，不启用服务器或云服务。构建前运行 `tools/fetch_python.py` 时，应用自带 Python 运行时，不需要本机安装；否则使用本机 Python 3.9+。不代表已完成 App Store 沙盒打包。

| 负责人 | 独占实现范围 | 验收 |
| --- | --- | --- |
| 集成 agent | `personal_os/cli.py`、`personal_os/legacy.py`、`personal_os/timer_bridge.py`、备份/构建脚本；计时引擎与 `sketchybarrc` 在同级 `sketchybar` 仓库修改，再把引擎同步到本仓库 `plugins/timer.py` | 旧数据兼容、单一计时账本、备份、原生构建、集成测试 |
| 目标与统计 agent | `personal_os/domain.py`、`tests/test_personal_domain.py` | 配置持久化、类别/目标可编辑、时长和有效天数分别计算 |
| 周期与复盘 agent | `personal_os/reviews.py`、`tests/test_personal_reviews.py` | 独立窗口/截止日期、逐期实例、补生成、复盘快照 |
| 前端 agent | `macos/PersonalOS/*.swift` | Dashboard/Time/Review/Settings、空状态/报错、原生操作、独立构建 |

跨模块更改先沟通，不互相改文件。新增中文文案要同时写英文：SwiftUI 视图里直接写字面量，其他地方用 `String(localized:)`，英文加到 `macos/PersonalOS/Localization/en.lproj`；Python 用 `_()` 并加到 `personal_os/i18n.py`。初始配置在 `personal_os/initial_profile.json`；个人真实历史和导出不提交仓库。

2026-11-06 起应用代码在本仓库，同级的 `sketchybar` 仓库只保留状态栏配置、计时引擎和部署脚本 `tools/install_mvp_timer.py`。

## Python 领域接口

domain：`connect(path)` 返回新应用 SQLite 连接；`get_profile(db)`；`save_profile(db, profile)`；`list_manual_activities(db)`；`add_manual_activity(db, payload)`；`delete_manual_activity(db, id)`；`build_statistics(profile, activities, first, last, today)`。日期均为 ISO 日期字符串，时间均为整数秒。初始化幂等；保存配置保留版本。

reviews：`initialize(db)`；`sync_occurrences(db, templates, today)`；`list_occurrences(db, today)`；`update_occurrence(db, id, status, text, today)`；`save_weekly_review(db, week_start, week_end, text, completed, statistics, profile)`；`list_weekly_reviews(db)`。任务实例有唯一 `(template_id,period_key)`，模板变更不覆盖已生成历史。

legacy：`read_activities(data_dir, first, last, now)` 返回 `(activities,timer_info,source_info)`，只读来源数据库和旧日志，不复制入新库；`preview` 活动明确 `saved=false`。

## 客户端接口

调用 `python3 <Resources>/backend/personal_os/cli.py`，工作目录为 backend 根，stdin 是单个 JSON 对象，stdout 只输出单个 JSON 对象；错误输出 `{"error":"可读说明"}` 并非零退出。应用设置目录默认 `~/Library/Application Support/Personal OS`，可用 `PERSONAL_OS_DATA_DIR` 覆盖。旧数据目录可用 `SKETCHYBAR_DATA_DIR` 覆盖。

action：

- `snapshot`：可选 `week_start`。返回下述完整状态。日期与周期模板未变时不写数据库。
- `save_profile`：`profile` 完整对象。返回 `{"ok":true}`。
- `timer`：`command` 为 start/pause/resume/stop/switch/discard/restore/tick/sleep/wake，可选 `category`。返回 `{"ok":true}`。
- `add_activity`：`day/category/seconds`，可选 `goal_ids`；`delete_activity`：`id`。仅编辑应用手工记录。
- `complete_task`：`id/status/text`，status=pending/completed/skipped。
- `save_review`：`week_start/text/completed`；统计由后端生成并固定，不接受客户端伪造快照。
- `export`：`path`，可选 `overwrite`；默认拒绝已有文件，仅在用户于保存框确认替换后传 `overwrite:true`。返回 `{"path":"..."}`。备份包括新库快照和旧来源快照（单文件 SQLite，无 WAL 旁文件）。
- `import`：`path`。恢复到新工作区并切换应用库；`workspace.json` 记录 `timer_dir`，已有计时记录时继续指向它，备份中的计时文件只作存档。

snapshot：`profile, today, week_start, week_end, statistics, timer, activities, tasks, reviews, trends, source`。

statistics：`work_seconds,total_seconds,research_seconds,research_days,reading_days,category_totals,days,goals`。category_totals 每项 `id/name/seconds`；days 每项 `day/seconds/work_seconds/by_category`。goals 每项 `id/name/kind/strength/actual/target/unit/status/progress`，unit=seconds/days，status=met/below/over/observing，可选 minimum/maximum。科研频率和阅读频率读取对应目标阈值，禁止前端重复计算。预览有单独字段，不计入正式统计。

timer：`mode/category/elapsed_seconds/running/active/available`。activities 每项 `id/day/category/seconds/source/precision/saved`；可选 goal_ids。已保存的旧数据 precision=day，不虚构时间轴。

tasks 每项 `id/template_id/name/description/period_key/visible_from/due_on/status/is_visible/is_overdue/completed_at/review_text`。完整任务列表返回未来和历史，首页仅显示 is_visible 且 pending，逾期单列。

reviews 每项 `id/week_start/week_end/text/completed/statistics/profile/updated_at`。trends 每项 `week_start/work_seconds/research_seconds`。source 至少含 `path/warnings`。

## 集成顺序

1. 四方按接口分别开发，三个子 agent 可并行，前端使用协议字段编译。
2. 集成 agent 接通真实来源，只在临时目录与备份副本进行写入测试。
3. 原生编译、启动与交互验收；共享计时适配在一致备份后部署。
4. 核对科研20h但3有效日、阅读3天各30min、月末7天窗口、重启持久化与旧数据完整性。
