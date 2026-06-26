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

### Фаза 3 — Architecture-pass над Roslyn (недели) — **дифференциатор**
Тонкий проход: Type→dependency граф (проекция символов Roslyn) + YAML-правила слоёв +
детект циклов. Это единственная реально новая мышца.
```yaml
rules:
  - id: UI001
    title: UI layer must not access SQL directly
    where: { typeNamespace: "*.UI.*|*.Presentation.*|*.ViewModels.*" }
    forbiddenDependencies:
      - "System.Data.SqlClient.SqlConnection"
      - "Microsoft.Data.SqlClient.SqlConnection"
      - "System.Data.DataTable"
    severity: error
```
Query-слой: **уровень 1 (YAML) + уровень 2 (C#-плагин `IAuditRule`)**. Свой DSL
(уровень 3, CQLinq/Cypher-подобный) — *отложить*, пока не ясно, какие запросы реально
нужны.
- *Граф строится там, где компилируется STS (стенд/Windows-CI с .NET); артефакт
  `graph.json` уезжает в дашборд и rules-движок.*

### Фаза 4 — Architecture Drift Report на PR (killer feature №1)
Поверх фаз 2+3:
```text
PR #1234 increased coupling in Broker.Documents by 18%.
New dependencies: Broker.Documents -> DevExpress.Xpf.Grid, -> System.Data.SqlClient
New cycle: Broker.Documents -> Broker.Services -> Broker.Documents
Risk: High — domain-ish module now depends on UI and SQL infrastructure.
```
Ревьюер читает и понимает: «провели канализацию через гостиную».

### Фаза 5 — Runtime correlation (killer feature №2) — Windows-only трек
```text
static:  subscribes to DocumentStore.Changed, no matching unsubscribe
runtime: 132 retained instances, held by static DocumentStore.Changed delegate
=> MEM-WPF-014: event leak confirmed, ~84 MB retained after closing window 10×
   confidence: high
```
ClrMD для live process / dump. Связывает static finding + heap retained path +
allocation stack + owning screen. Исходная цель проекта, упакованная в продукт.

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
