# План работ: Own.NET → CoStrict-friendly

> **Статус: рабочий план, нормативный для развилок размещения и инвариантов.**
> Цель — сделать Own.NET пригодным для LLM-агентов (в первую очередь CoStrict)
> не через «агент читает наши отчёты», а через машинный контракт: единый CLI,
> стабильные JSON-схемы findings, evidence-first, patch-артефакты с проверкой,
> честный coverage. Документ фиксирует, **что делаем, где, в каком порядке и
> чего сознательно не делаем**.

Связанные документы: исходный CoStrict-план (внешний), `Own.NET/Plan.md` (аудит),
`OwnAudit/docs/fix-arm.md` (fix-arm), `Own.NET/docs/notes/roslyn-tools-and-cli.md`
(почему CLI-first и почему «один чекер»).

---

## 0. Реальность против исходного плана (зафиксировать, чтобы не расползлось)

Исходный CoStrict-план написан под воображаемую архитектуру (`Own.Net.Core` на
Roslyn semantic model + `Own.Net.Indexer` с symbol/call/type-графами + персистентный
индекс). **Этого в репозитории нет и по дизайну быть не должно.** Фактически:

- **Own.NET** = Python-движок `ownlang/` (ownership/borrow-checker, лоуэрит в C#)
  **+** `audit/` — Python-оркестратор, гоняющий готовые анализаторы (own-check,
  XAML, Roslyn-паки, CodeQL, Infer#), нормализующий их SARIF, скорящий по
  cross-tool agreement и рендерящий health-отчёт.
- **C#-сторона** (`frontend/roslyn/OwnSharp.Extractor`) — **намеренно НЕ чекер, а
  fact-extractor**: `.csproj → facts.ownir.json`. Высечено в
  `docs/notes/roslyn-tools-and-cli.md`: *«Do not reimplement the checker in C#.
  One checker; the C# side feeds it»*. Полный C#-семантический фронтенд отвергнут
  как «human-years».
- **OwnAudit** = lift-out home + **реально работающий fix-arm** (propose/apply/verify
  с regression-gate) + `arch/` + валидированный прогон по STS (380 findings).
- Вывод **уже** идёт в SARIF + собственный JSON. **Нет** единого CLI: точки входа
  разрозненны (`python -m ownlang`, `python -m fixarm.cli`, `Run-Audit.ps1`, …).

Из этого вытекает: «семантический оракул с symbol-графом», вокруг которого
построен исходный план, — это ровно тот слой, который команда сознательно
**не строит**. Поэтому ниже — что дёшево, что дорого, **и что нельзя**.

---

## 1. Решения по размещению

| Артефакт | Репозиторий | Обоснование |
|---|---|---|
| Реализация CLI `ownnet` (Python-фасад) — **near-term** | **OwnAudit** | здесь активная разработка (см. §1a); CLI-модули (`report/`, `fix/`, `arch/`) и mutating-поверхность (fix-arm) уже тут |
| Дом `ownnet` + аудита — **destined** | **Own.NET** | конечная архитектура: всё консолидируется в Own.NET (см. §1a); split — временное удобство |
| Контракты: `ownnet.finding.v1`, `spec/ownnet-cli.md`, `ownnet.facts.calls.v1` | **Own.NET/spec** | `spec/` там уже нормативный (`CLI.md`, `Diagnostics.md`); схема версионируется вместе с движком — согласованность by construction |
| `.costrict/` pack (tools/skills/agents), `AGENTS.md` | **OwnAudit** (отдельная папка) | agent-facing packaging, снаружи core |
| Call-facts слой (`method_invokes` и т.п.) | **Own.NET/frontend/roslyn** (extractor) | новый `kind` факта на существующей fact-машине, не второй чекер |

### 1a. Стратегия репозиториев (решено 2026-06-26)

**Конечный дом аудита и `ownnet` — Own.NET.** Split Own.NET/OwnAudit — временное
удобство, не целевая архитектура (`audit/` decoupled и лифтабельный, `Plan.md §7`;
decoupling — это CI-grep-правило, а не репо-граница).

**Подтверждено по коммитам:** `Own.NET/audit/` заведён 2026-06-24 (25 коммитов) —
это *база*. `OwnAudit` заскаффолжен 2026-06-25 как «STS audit orchestrator» — взял
базу и «довёл до ума»: слои `fix/`+`arch/`+`oracle/`+GitHub-facing `report/` +
P-015 evidence набрали 42 коммита и впереди по функционалу. Core-aggregate
(normalize/score) в Own.NET ещё живой и драйвится из OwnAudit через worktree —
полного форка нет.

**Решение (владелец):** консолидацию в Own.NET **НЕ делаем сейчас** — допилы
продолжаются в OwnAudit, сливать всё преждевременно. В Own.NET — **только
документация-якорь** (баннер-статус в `Own.NET/audit/README.md`), чтобы копия там
не воспринималась как актуальная. Поэтому:

- **Near-term:** `ownnet` строится **в OwnAudit** (где живой аудит + fix-arm).
- **Контракты** (`spec/ownnet-cli.md`, `finding.v1`) — всё равно в **Own.NET/spec**,
  рядом с движком (со-локально с будущим домом; малозатратно держать там уже сейчас).
- **Destined:** при консолидации `ownnet` и аудит переезжают в Own.NET; cross-repo
  пин тогда исчезает сам.

**Язык CLI — Python, не .NET/System.CommandLine.** Почти вся оркестрируемая логика
(`audit/aggregate`, `fixarm`, `arch`, `report`) — Python; C# — только extractor и
stub'ы. .NET-фасад означал бы subprocess-мост `dotnet → python` на каждую команду.
System.CommandLine-скелет `own-audit` остаётся под C#-native поверхность
(extractor/runtime), а не под `audit/propose`. Для агента язык фасада безразличен —
`.costrict/tools/ownnet.ts` дёргает бинарь `ownnet` независимо от реализации.

---

## 2. Несущие стены (инварианты — нарушать нельзя)

Эти правила отделяют «дорого, но можно» от «можно, но нельзя». Каждое — кандидат
в CI-проверку.

1. **Decoupling.** CLI/MCP/costrict-pack **не кладём** в `ownlang/` или `audit/`.
   CI-grep уже запрещает `import ownlang` в `audit/` (`Plan.md §7`) — расширить на
   «core не знает про CoStrict».
2. **Один чекер.** Symbol/call-facts — только как расширение `OwnSharp.Extractor`
   (эмитит факты), **не** как второй чекер на C#, выносящий вердикты. Разрешение
   target'ов, требующее dataflow → факт помечается `unknown`, ребро не дорисовывается.
3. **Regression-gate не обходим.** `propose/apply` всегда идут через
   `fix/fixarm/orchestrate.run_fix()` (dry-run → re-audit → reject-if-new).
   Auto-apply мимо гейта запрещён; `apply` = deny/ask по умолчанию.
4. **Честный confidence.** Один словарь на findings и call-facts: `high` /
   `candidate` / `unknown` (как `score.py` agreement), **не** float `0.91`.
   Severity (`P0..P3`) — отдельная ось, не схлопывать с confidence.
5. **Честный coverage.** `ownnet audit` никогда не «зелёный по умолчанию»: всегда
   рапортует, какие tier'ы отработали, какие пропущены и почему. Пропущенный tier
   ≠ «чисто».
6. **Stateless / on-demand.** Call-facts и refs пересчитываются по запросу для
   целевого символа. Персист edge-table между запусками = построили отложенный
   дорогой импакт-индекс. Кэш можно; второй дрейфующий стейт — нет.

---

## 3. Контракт Linux / Windows (tiering)

Граница проходит не «Linux-фичи / Windows-фичи», а **«генерируется на венде» /
«потребляется везде»**. Потребление (normalize→score→report) — кроссплатформенный
Python всегда.

| Tier | Что | Генерация SARIF | Агрегация |
|---|---|---|---|
| **T0 build-free** | own-check, CodeQL `--build-mode=none`, XAML facts | где угодно (Linux/CI) | где угодно |
| **T1 build-required** | Roslyn-паки (MSBuild), Infer# (WSL) | только Windows-stand | где угодно (Python) |
| **T2 runtime** | LeakHarness / PropertyChangedStorm / DuplicateDetector | Windows + запущенное приложение | где угодно (`ingest.py`→SARIF) |

`run_static.py` уже continue-on-error: подбирает любой готовый SARIF из `artifacts/`,
делает честный частичный отчёт. Linux-агент получает T1/T2-findings либо из
заранее снятого на венде артефакта (пример: `sts_audit/findings.json`, 380 findings),
либо честно видит gap. **CLI оркестрирует/ингестит T1/T2, не переписывает их.**

---

## 4. Фазовый план

### Phase 1 — MVP (CLI + контракт + интеграция)

Цель: рабочий `ownnet` + `finding.v1` + CoStrict pack. **Без** symbol-index,
query-lang, sql-compat.

| # | Задача | Репо | Оценка |
|---|---|---|---|
| 1.1 | `spec/ownnet-cli.md` + JSON-схема `ownnet.finding.v1` (id-fingerprint, kind, severity, confidence `high/candidate`, locations, tier, evidence, suggestedFixes, validation) | Own.NET | малая (1–2 дня) |
| 1.2 | Python-фасад `ownnet` (точка входа поверх существующих модулей) | OwnAudit | средняя (нед.) |
| 1.3 | `ownnet audit` — auto-detect среды, T0 in-process + ингест готовых T1/T2 SARIF, **секция coverage**; флаги `--top`, `--summary`, `--tier`, `--confidence` (agent budget) | OwnAudit | средняя |
| 1.4 | `ownnet status` — доступные tier'ы в текущей среде | OwnAudit | малая |
| 1.5 | `ownnet explain <finding-id>` — детали + evidence по стабильному id | OwnAudit | малая–средняя |
| 1.6 | `ownnet propose fix <id>` / `ownnet verify patch <file>` — обёртка над `fixarm` (unified-diff, regression-gate обязателен) | OwnAudit | средняя |
| 1.7 | `ownnet report` — md/sarif/json summary (поверх `report.cli`) | OwnAudit | малая |
| 1.8 | `.costrict/tools/ownnet.ts` (audit/explain/propose/verify), `skills/` (safe-refactor, wpf-audit), `agents/` (ownnet-reviewer, read-only), `AGENTS.md`; права: read-only default, propose=ask, apply=deny | OwnAudit | малая |
| 1.9 | CI: сборка/прогон T0 на Linux, проверка формата `finding.v1`, smoke propose/verify на фикстуре | OwnAudit | малая |

**Definition of done Phase 1:** агент через CoStrict делает
`audit → explain → propose → verify` на Linux над T0 (+ ингест Windows-артефакта),
получая стабильные id и честный coverage.

### Phase 2 — Call-facts (evidence для безопасного рефакторинга)

Stateless, on-demand. Каждый уровень — отдельный opt-in fact kind с явным confidence.

| # | Задача | Репо | Оценка |
|---|---|---|---|
| 2.1 | `spec` + схема `ownnet.facts.calls.v1` (from/to symbolId, kind, confidence, source) | Own.NET | малая |
| 2.2 | Level 1: direct call facts в `OwnSharp.Extractor` (invocation, ctor, property get/set, event add/remove, lambda-body calls) | Own.NET | средняя |
| 2.3 | `ownnet refs <symbol>` / `ownnet explain symbol <symbol>` — reverse lookup по запросу (без импакт-обещаний) | OwnAudit | средняя |
| 2.4 | Level 3: XAML Command/Binding join поверх готовых `xaml_facts` (binding-path → C#-символ), отдельный граф | Own.NET | средняя |
| 2.5 | Level 2: conservative virtual/interface expansion (`possibleTargets` + `candidate`) | Own.NET | средняя |

**Главный ROI Phase 2:** честные `unknown`-корзины (reflection/DI/XAML not expanded)
не дают агенту удалить метод, достижимый только через XAML Command/event.

### Phase 3+ — Отложено (НЕ обещать в MVP)

Дорого и/или граничит с нарушением «одного чекера». Вводить только по реальному
запросу, по одной фиче.

- MCP-сервер (обёртка над уже доказанным CLI; read-only-first).
- Level 4 DI-aware call expansion (поверх существующего `di.py` registration-графа).
- `ownnet impact --diff` (требует stable symbol IDs).
- Персистентный symbol/edge индекс `.ownnet/*.db` (см. инвариант §2.6 — риск).
- Semantic query language (`query "classes where fanOut>30 and has WpfBinding"`).
- `taskpack` для StrictPlan/Strict Mode.
- sql-compat анализатор (net-new, вне WPF/lifetime-фокуса).
- precise whole-program call graph — **не делаем**.

---

## 5. Матрица статуса возможностей (на момент написания)

| Возможность | Статус | Где / почему |
|---|---|---|
| SARIF output | ✅ есть | `audit/aggregate/report.py:render_sarif`; `ownlang ownir --format sarif` |
| JSON findings | ✅ есть (reshape под v1) | `report.py:render_json` |
| read-only vs mutating split | ✅ есть | audit read-only; fix-arm отдельно, tier-gate |
| propose/apply/verify + regression-gate | ✅ есть (CI/Linux, Windows-stand pending) | `fix/fixarm/{own_fix,orchestrate,appliers}.py`, 6/6 тестов |
| evidence-first (own-check/DI/runtime) | 🟡 частично | `ownlang/evidence.py`, `di.py`; сторонние тулзы дают только file:line |
| структурный DI registration-граф | ✅ есть (для lifetime) | `ownlang/di.py` |
| XAML binding/command/event facts | 🟡 факты есть, join pending | `audit/static/tools/xaml_facts.py` |
| единый CLI | ❌ нет | разрозненные точки входа |
| stable finding IDs | ❌ нет (fingerprint на aggregate) | диагностики rule-coded (`OWN001`) |
| symbol IDs / call graph / references | ❌ нет | строится в Phase 2 как call-facts |
| impact --diff | ❌ нет | Phase 3 |
| persistent index | ❌ нет | Phase 3, под риском |
| semantic query lang | ❌ нет | Phase 3 |
| sql-compat | ❌ нет вообще | Phase 3, net-new |
| runtime wpf-events/propertychanged/static-candidates | 🟡 есть, Windows + running app | `audit/runtime/*` |

---

## 6. Решённое и открытое

**Решено (2026-06-26):**
- Дом аудита и `ownnet` — Own.NET (destined); консолидация **отложена**, допилы
  в OwnAudit, в Own.NET — только документация-якорь (см. §1a).
- Near-term `ownnet` строится в OwnAudit; контракты — в Own.NET/spec.
- Пин Own.NET в OwnAudit: пока остаётся worktree-подход `Run-Audit.ps1`; при
  консолидации вопрос снимается (один репозиторий).

**Открыто:**
1. Имя бинаря: `own-audit` → `ownnet` rename или новый entry point рядом?
2. Дистрибуция Python-CLI: `uv tool` / `pipx` — целевой способ установки для
   агентских окружений.
3. Версионирование схем: `ownnet.finding.v1` changelog — `Own.NET/spec/`
   (предложение), рядом с движком.
4. Триггер консолидации: какой признак «допилы устаканились» запускает Phase 0
   (перенос в Own.NET) — зафиксировать критерий, чтобы дрейф двух копий не рос
   бесконечно.
