# Own.NET Auditor — дорожная карта

Статус: vision + фазовый план, не реализация. Приземляет идею «сделать из Own.NET
аудиторскую тулзу уровня NDepend + Joern + WPF-инспектор» на **существующую** кодовую
базу OwnAudit, чтобы это был набор обозримых инкрементов для соло-разработчика, а не
многолетний продукт с нуля.

Связанные доки: [`fix-arm.md`](fix-arm.md) (тиры, safety contract, diff/baseline),
[`audit-data-leverage.md`](audit-data-leverage.md) (метрики, FP-rate, побочные продукты).

## 0. Тезис

Не клонировать NDepend (путь «мы написали NDepend, только хуже и со своим форматом
боли»). Моат в том, что generic-тулзы видят только complexity/coupling, а под легаси
.NET 4.7.2 / WPF / DevExpress нужно видеть:

- почему окно не выгружается,
- почему справочник размножился 999 раз,
- почему ViewModel держит полбазы,
- почему слой презентации полез в SQL,
- почему PropertyChanged устроил DDoS самому себе.

Что забрать идеологически (не кодом):
- **NDepend** — метрики + dependency graph + quality gates + baseline + custom queries.
- **Joern** — модель `code → Code Property Graph → query DSL → findings`.
- **CodeQL** — «код как база данных, по которой пишутся запросы».
- **Roslyn** — семантический слой (`SemanticModel`/symbols), без него AST = «угадай,
  какой `Save()` имелся в виду».

Целевая форма:
```text
Own.NET Auditor =
  semantic code graph
  + architecture rules
  + WPF/runtime-specific probes
  + baseline/diff
  + SARIF/GitHub reports
  + AI explanation layer
```

## 1. Главная поправка: это не гринфилд

Вижн написан как «строим аудитор с нуля». Но половина уже есть в OwnAudit — фрейм
должен быть **«достраиваем недостающие слои»**, а не «начинаем заново».

| Из вижна | Что уже есть в OwnAudit | Реальный гэп |
|---|---|---|
| findings + evidence модель | `sts_audit/findings.json` (tool/path/line/rule/category/resource/message) | evidence-рёбра графа (type→type, call) |
| CLI `ownnet-audit scan` | Own.NET/audit оркеструет Roslyn + CodeQL + InferSharp + own-check | architecture-pass, SARIF/baseline вывод |
| baseline + diff (MVP-2) | fix-arm `diff_findings(before, after)` | обёртка «fail только за новый мусор» |
| graph.json вывод | дашборд рендерит treemap/drill-down/тиры | сам граф как артефакт |
| debt-delta / тренд | `viz/history.jsonl` (снимок на прогон) | per-PR risk score |
| тиры/квалити-гейт | `fixarm.tiers` (T1–T4 + gate) | quality-gate как pass/fail в CI |
| локальные smells (leak/coupling) | анализаторы: 17k inpc, 2.4k idisposable, 380 own-check | **cross-cutting** архитектурные правила |

Вывод: переоценка с «многолетний продукт для команды» на «3 недостающих слоя поверх
имеющегося».

## 2. Три острых предупреждения

**2.1. Не переписывать семантический слой Roslyn.** В вижне мелькает «AST Own.NET /
semantic model Own.NET» — ловушка на полгода. У Roslyn уже есть `SemanticModel` /
`SymbolInfo` / `Compilation`. Граф = **проекция над символами Roslyn**, а не новый
компилятор. Mono.Cecil/dnlib подключать только для IL-уровня бинарей без исходников
(DevExpress).

**2.2. Граф оправдывать архитектурой, а не метриками.** Coupling/complexity/leaks на
*локальном* уровне анализаторы уже ловят. Чего они НЕ умеют — *cross-cutting*
рассуждение: «этот Presenter тащит SQL+DevExpress+DataTable через границу слоя». Только
это оправдывает граф. Переизобретать LCOM, который и так есть, — мёртвый груз. 40 метрик
из вижна туда же: ценность в 3–4 **составных диагнозах**, а не в сорока счётчиках:

```text
God Class      = methods>T AND fields>T AND ext_deps>T AND cohesion<T
Toxic Presenter= ns ~ *.UI.*|*.Presentation.* AND uses SqlConnection/DataTable/File/Thread.Sleep
Domain Pollution = ns ~ *.Domain.* AND depends on WPF/DevExpress/System.Windows
```

**2.3. Runtime-трек — Windows-only, секвенировать отдельно.** Static-граф + правила +
SARIF строятся и тестируются в CI (Linux, без .NET — как весь fix-arm). ClrMD/heap-
correlation физически живут только на стенде. Не смешивать в один спринт. NB:
runtime-корреляция — это буквально исходная **«стадия 2 / рантайм-анализ»**, с которой
проект начинался; вижн замкнул круг.

## 3. Фазовый план (дешёвое — первым, переиспользуя имеющееся)

### Фаза 1 — SARIF-экспорт (дни)
Существующий `findings.json` → SARIF 2.1.0 → GitHub code scanning alerts. Данные уже
есть. Лимит аннотаций GitHub (50/req) → выгружать по severity, не вываливать 9000.
Артефакты: `ownnet-audit.sarif`, `report.md`, `metrics.json`.
- *Строится в CI.* Тестируется на фикстурах, как fix-arm.

### Фаза 2 — Baseline + diff ✅ реализовано (`report/baseline.py`, `report/diff_cli.py`)
Гейт: **валим только за новый мусор**, не за GodService 2014 года. `baseline.json` +
`current.json` → delta-report (new/fixed/net debt-delta) + exit-код для CI.
- Идентичность находки — тот же стабильный fingerprint, что у SARIF-экспортёра (rule +
  path + нормализованное сообщение, per-occurrence), поэтому гейт и code-scanning алерты
  сходятся в том, что считать «той же находкой». Это устойчиво к сдвигу строк и к
  изменению идентификаторов/чисел в сообщении. (Не `diff_findings` из fix-arm — тот для
  before/after одного фикса на одном дереве, а не для сравнения двух прогонов корпуса.)
- `python3 -m report.diff_cli --save-baseline` — снять baseline (компактный: fingerprint
  + rule/path/cat/tool, без длинных сообщений); затем `--baseline … [--gate-level
  note|warning|error] [--report-only]` — гейт. Exit 0 = чисто, 2 = есть новый долг ≥ уровня.
- *Строится и тестируется в CI* (`report/tests/test_baseline.py`, 7/7). Baseline —
  пользовательский артефакт (создаётся на стенде, в `.gitignore`).

### Фаза 3 — Architecture-pass над Roslyn (недели) — **дифференциатор** ✅ движок готов
Тонкий проход: Type→dependency граф (проекция символов Roslyn) + правила слоёв +
детект циклов. Это единственная реально новая мышца.

**Сплит — как и везде в проекте: тяжёлый .NET на стенде, разбор на Python в CI.**
Roslyn-экстрактор (на стенде, где STS компилируется) выдаёт `graph.json` (контракт —
`docs/arch-graph.md`); Python-движок (`arch/`, stdlib-only, тестируется в CI) его читает
и выдаёт находки **в той же схеме `findings.json`** (tool `own-arch`, category
`architecture`), так что они идут в SARIF/diff/дашборд без изменений.

Четыре вида правил (`arch/rules.json`):
- **layering** (ключ `layers`) — запрещённое направление (`ARCH-UI-SQL`: UI→SQL,
  `ARCH-DOMAIN-WPF`: Domain→WPF). Источник обязан быть internal (наш — нам и чинить); цель
  может быть и внешним фреймворком. Паттерны — case-sensitive fnmatch по
  namespace/FQN/assembly/имени.
- **cycles** — `ARCH-CYCLE-TYPE|NS|ASM`: Тарьян SCC (итеративный — namespace-граф STS
  достаточно глубок, чтобы уронить рекурсию), SCC размером >1 = цикл; NS/ASM сворачиванием
  type-графа по `namespace`/`assembly`.
- **god_class** — составной сигнал `ARCH-GOD-CLASS`: тип, пересёкший ≥ `min_signals` порогов
  из {methods, fields, loc, deps_out} одновременно. `deps_out` берётся из рёбер графа, не из
  метрик, — чтобы его нельзя было занизить устаревшей метрикой.
- **coupling** — метрики Мартина (`arch/metrics.py`) на namespace/assembly: афферентность
  `Ca`, эфферентность `Ce`, нестабильность `I = Ce/(Ca+Ce)`. Два под-правила:
  `ARCH-SDP` (Stable Dependencies — стабильный компонент зависит от менее стабильного,
  `I(from)+min_gap < I(to)`) и `ARCH-UNSTABLE-HUB` (компонент с высокими и `Ca`, и `Ce` —
  изменение бьёт в обе стороны). Находки на уровне компонента (namespace в `resource`).

**Простое, но расширяемое без рефакторинга** — `component_metrics()` единая точка роста:
- **Abstractness `A` + Distance from main sequence `D = |A+I−1|`** считаются *автоматически*,
  как только узлы графа начнут нести флаг `is_abstract` (до тех пор — `None`, фича дремлет,
  правила/вызовы не меняются). Это +1 булево поле в экстракторе.
- **Cohesion (LCOM)** — намеренно *не здесь*: нужен member-граф (метод↔поле), отдельное
  расширение контракта. Когда появится — это новый `arch/cohesion.py`, текущий код не трогает.

```jsonc
// arch/rules.json — JSON, не YAML: CI использует только actions/setup-python и не ставит PyYAML
{ "layers": [ { "id": "ARCH-UI-SQL", "from": ["Sts.UI.*", "*.ViewModels.*"],
               "to": ["*.Data.Sql*", "System.Data.SqlClient*"], "message": "UI → SQL" } ],
  "cycles": { "type": true, "namespace": true, "assembly": true },
  "god_class": { "id": "ARCH-GOD-CLASS", "min_signals": 2,
                 "methods": 40, "fields": 25, "loc": 1000, "deps_out": 30 },
  "coupling": { "level": "namespace",
                "sdp": { "id": "ARCH-SDP", "min_gap": 0.3, "min_ce": 4 },
                "unstable_hub": { "id": "ARCH-UNSTABLE-HUB", "min_ca": 8, "min_ce": 8 } } }
```
- `python3 -m arch.cli --graph sts_audit/graph.json` → `arch/out/arch-findings.json` +
  `arch-report.md`. Detect-only (exit 0); гейтить — через `report.diff_cli`.
- Метрики `component_metrics()` — фундамент **фазы 4** (Architecture Drift: дельта Ca/Ce/I
  между прогонами).
- *Строится и тестируется в CI* (`arch/tests/test_arch.py`, 32/32, и под `-O`).
- Query-слой: **уровень 1 (JSON-правила) готов + уровень 2 (C#-плагин `IAuditRule`)** —
  отложен на сторону экстрактора. Свой DSL (уровень 3, CQLinq/Cypher-подобный) — *отложить*,
  пока не ясно, какие запросы реально нужны.
- *Граф строится там, где компилируется STS (стенд/Windows с .NET); экстрактор — sketch в
  `docs/arch-graph.md`, в этот repo не коммитится (нужен .NET SDK).*

### Фаза 4 — Architecture Drift Report на PR (killer feature №1) ✅ движок готов
Поверх фаз 2+3. Фаза 2 диффит *находки* (видит нарушение, только когда оно перешло порог
правила); drift — дополнение: диффит **саму структуру** между двумя прогонами (baseline =
граф main, current = граф PR) и репортит, что *сдвинулось*, ещё до того как это станет
находкой.

`arch/drift.py` + `arch/drift_cli.py` (stdlib-only, в CI):
- **snapshot** графа — компактный: метрики на компонент + namespace-поверхность зависимостей
  (включая рёбра во внешние фреймворки — там и живёт «new SQL dependency») + множество циклов.
  Baseline-снапшот — **пользовательский артефакт**, как baseline фазы 2: снимается на стенде с
  графа main, держится **вне git** (`.gitignore`) и подаётся в CI как артефакт; сгенерированные
  снапшоты не коммитим.
- **diff** двух снапшотов → risk-tagged items: новые/убранные циклы (type/ns/asm), новые/убранные
  зависимости, скачки coupling (`Ce`), сдвиги нестабильности. Пороги — в `arch/rules.json`
  (`drift`-блок). Новая зависимость в `sensitive_targets` (SQL/WPF) = **High**.
- **gate**: `--gate-level high|medium|low` → exit 2 на дрейфе ≥ уровня (по умолчанию
  report-only). Рендерит PR-friendly `drift.md`.

```text
# на стенде: снять снапшот архитектуры main, затем на PR диффнуть граф PR против него
python3 -m arch.drift_cli --graph main_graph.json --save-snapshot --snapshot arch-snapshot.json
python3 -m arch.drift_cli --graph pr_graph.json   --baseline arch-snapshot.json --gate-level high
```
Пример вывода `drift.md` (проверено на синтетическом стенде):
```text
4 High · 3 Medium · 1 Low — architecture change(s) vs baseline.
🔴 High: new namespace cycle: Sts.Broker.Services, Sts.Domain.Orders
🔴 High: new dependency: Sts.Domain.Orders → System.Data.SqlClient
🟠 Medium: Sts.UI.ViewModels: efferent coupling Ce 21 → 27 (+6, +29%)
```
Ревьюер читает и понимает: «провели канализацию через гостиную». *Тестируется в CI*
(`arch/tests/test_arch.py`, 41/41, и под `-O`).

### Фаза 5 — Runtime correlation (killer feature №2) ✅ движок готов (Python-сторона)
```text
static:  subscribes to DocumentStore.Changed, no matching unsubscribe
runtime: 132 retained instances, held by static DocumentStore.Changed delegate
=> event leak confirmed, ~84 MB retained after closing window 10×
   confidence: high
```
Исходная цель проекта, упакованная в продукт. Тот же сплит: heap-dump коллектор (ClrMD /
dotnet-gcdump) гоняет сценарий N× на стенде и выдаёт `runtime.json` (контракт —
`docs/runtime-contract.md`); Python (`runtime/`, stdlib-only, в CI) коррелирует находки с
удержанием.

`runtime/correlate.py` + `runtime/cli.py` — **трёхсторонний сплит** (ровно FP-rate/blind-spot
триага из §audit-data-leverage):
- **confirmed** — static-находка о течи + heap-удержание совпали → находка в схеме `findings.json`
  (tool `own-runtime`, category `runtime-confirmed-leak` → SARIF `error`) с `confidence`.
  `count − expected ≥ min_count` подтверждает; `≥ high_count` **или** удержание
  `static-event`-делегатом → **high** (классическая WPF event-leak с поличным).
- **static-only** — находка есть, удержания нет → **вероятный ложняк** / путь не покрыт сценарием.
- **runtime-only** — удержание есть, статика молчала → **слепое пятно** анализатора (кандидат на
  новое правило).
- `python3 -m runtime.cli --findings … --runtime … [--gate-level high]` → `runtime-findings.json`
  + `runtime-report.md`. Гейт по `--gate-level` (exit 2 на confirmed ≥ confidence).
- *Тестируется в CI* (`runtime/tests/test_runtime.py`, 12/12, и под `-O`). Коллектор дампа —
  sketch в `docs/runtime-contract.md`, на стенде (нужен CLR + живой STS), в repo не коммитится.

### Отложено сознательно
- Свой query-DSL (CQLinq/CodeQL-подобный) — после YAML + C#-плагинов.
- Зоопарк из 40 метрик — вместо них 3–4 составных диагноза.
- AI explanation layer — поверх стабильных findings+evidence (переиспользует локальный
  AI-фиксер из fix-arm: тот же «модель объясняет, человек судит»).

## 4. WPF-аудит пак (фаза 3.5, когда граф есть)

Где Own.NET может быть сильнее NDepend/Joern под этот проект:
- **event leaks**: `+=` без `-=`, static-event подписки,
  `DependencyPropertyDescriptor.AddValueChanged`, `CollectionChanged`/`PropertyChanged`.
- **timers**: `DispatcherTimer`/`Timers.Timer`/`Threading.Timer` без Stop/Dispose.
- **binding**: несуществующий path, binding к тяжёлому свойству, `ElementName`/
  `RelativeSource`-ад, runtime binding errors из лога.
- **PropertyChanged hell**: каскадные уведомления, дубли в циклах, UI-thread storms.
- **virtualization**: `ItemsControl`/`ListView`/`GridControl` с выключенной
  виртуализацией, вложенные `ScrollViewer`, тяжёлые `DataTemplate`.
- **freezable**: `Brush`/`Geometry`/`ImageSource` не frozen; повторяемые immutable-
  ресурсы вместо shared/static.
- **data duplication**: immutable-справочники размножаются по VM/DTO.

Часть уже покрыта own-check (subscription/region-escape) и WpfAnalyzers (3 902
wpf-freezable) — пак расширяет, не дублирует.

## 5. Что брать готовое

| Слой | Инструмент |
|---|---|
| семантика | Roslyn `SemanticModel` / Workspaces |
| IL/metadata | Mono.Cecil или dnlib (только для бинарей без исходников) |
| runtime/dump | ClrMD |
| вывод | Microsoft SARIF SDK (.NET) |
| индекс/хранилище графа | SQLite / DuckDB; сериализация JSON/MessagePack |
| inspiration для arch-правил | ArchUnitNET, NetArchTest (посмотреть API-дизайн, не обязательно встраивать) |

## 6. Модель finding (целевая, расширяет текущую)

```json
{
  "id": "ARCH-UI-SQL-001",
  "severity": "error",
  "title": "UI layer directly depends on SQL",
  "location": { "file": "Views/DeclarationPresenter.cs", "line": 142 },
  "subject": "DeclarationPresenter",
  "evidence": [
    { "kind": "type_dependency", "from": "DeclarationPresenter", "to": "System.Data.SqlClient.SqlConnection" },
    { "kind": "call", "method": "OpenConnection", "line": 142 }
  ],
  "recommendation": "Move database access behind application service/repository boundary.",
  "confidence": 0.93,
  "tags": ["architecture", "layering", "legacy-wpf"]
}
```
Текущий `findings.json` уже близок (tool/path/line/rule/category/resource/message) —
добавляются `evidence[]`, `subject`, `confidence`, `recommendation`. Это позволяет:
показать в HTML, отдать в GitHub SARIF, сравнить с baseline, отдать AI на объяснение,
агрегировать в метрики.

## 7. Метрики (по готовности данных)

- *Бесплатно сейчас (есть):* concentration/top-N, signal density по тулу,
  corroboration rate, fixability coverage — см. `audit-data-leverage.md`.
- *Нужен граф (фаза 3):* Ca/Ce/Instability, dependency cycles (assembly/ns/type),
  layer violations, forbidden-dependency count, fan-in/out, God/Toxic/Pollution-диагнозы.
- *Нужен runtime (фаза 5):* retained count/bytes by type, static-root retention,
  duplicate immutable data, Brush/Geometry duplication, LOH/bitmap suspects.
- *Нужно ≥2 прогона (база есть):* new/fixed findings, debt delta, new cycles,
  changed public API surface, risk score per PR, hotspot files touched.

## 8. Вердикт

Вижн как **north star** — крепкий, инстинкты верные (findings+evidence, baseline-diff,
drift-report, runtime-correlation, не клонировать NDepend). Реализовывать **не как новый
CLI с нуля, а как фазы поверх OwnAudit**:

1. SARIF + baseline/diff — почти бесплатно, переиспользует fix-arm.
2. Architecture-pass над Roslyn — единственная реально новая мышца; граф узко под
   layering/drift, семантику не писать — брать Roslyn.
3. Drift-report на PR — killer feature №1.
4. Runtime correlation — отдельный Windows-трек, killer feature №2, замыкает исходную
   цель проекта.

Не начинать с «сделаем всё». Начинать с graph + rules + baseline. Иначе получится не
NDepend, а NDependsOnEverything — концептуально честно, архитектурно похороны.
