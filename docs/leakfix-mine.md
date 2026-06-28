# LeakFixMine — методика майнинга leak-фиксов и честной оценки OwnAudit

Статус: реализованный research-пайплайн (`leakmine/`) + методика. Код — чистый stdlib,
тесты офлайн (`leakmine/tests/test_leakmine.py`). Это **исследовательская рука** датасет-
истории (см. `audit-data-leverage.md §3`): корпус из исправленных багов — это
регрессионный набор и материал для статьи, **а не** знаменатель recall. Поэтому половина
работы тут — отделять сигнал от везения.

## 0. Зачем

Два результата за одну работу:

1. **Практика для OwnAudit** — реальный корпус «было/стало», регрессионные тесты,
   приоритизация правил по данным, таблица «мы vs baseline-линтеры».
2. **Публикация** — «прогнали на N реальных leak-фиксах в .NET/React/Android/Java;
   baseline ловит X%, OwnAudit — Y%, и Z уникальных, с объяснением пути удержания».

Главный принцип: **не переобещать**. Цифры ниже честны ровно в тех границах, в которых их
можно защитить.

## 1. Три независимых эксперимента (не один)

Корпус исправленных багов смещён by construction — в него попадают только баги, которые
(а) заметили, (б) диагностировали, (в) починили и (г) описали leak-словами. Поэтому recall
по нему — это recall **по корпусу**, а не «по всем течам». Чтобы закрыть смещение, у нас
три дизайна, и они дополняют друг друга:

| Дизайн | Что меряет | Защита от смещения | Модули |
|---|---|---|---|
| **Fixed-bug corpus** | regression-recall, уникальные находки | SZZ-привязка + before/after | `collect` → `signals` → `szz` → `confirm` → `metrics` |
| **Prospective sweep** | precision в дикой природе | сэмплируем *весь живой код*, не «уже починенное» | `sweep` |
| **Time-travel** | lead time («поймали бы раньше людей») | смотрим вперёд по истории | `szz.lead_time` |

Самый сильный для adoption — **prospective sweep**: он уже сработал в зародыше на OwnTS
(реальные useEffect-течки в популярных npm). Fixed-bug corpus понижен до роли регрессий.

## 2. Хранилище

Один SQLite-файл (`schema.py`), пять таблиц-спина: `candidates → patches → labels →
tool_runs → verdicts`. Находки и вердикты лежат JSON-блобами (они вложенные), реляционная
часть — только чтобы возобновлять прогон и джойнить стадии. SQLite, не DuckDB — stdlib, CI
ничего не ставит.

## 3. Классификация фиксов — дёшево и детерминированно сначала

Сначала **не** LLM. Сначала patch-сигналы (`signals.py`): что патч *добавил* и *удалил*.
Скоринг как в плане:

```
+3 leak-keyword в title,  +2 в body
+weight за каждый сматченный patch-сигнал (настоящая улика)
+2 changed-file с релевантным расширением
-3 только docs,  -4 только bump зависимостей
score >= 7  -> кандидат
score >= 10 -> вероятный фикс
```

Категории — **тот же таксон, что в `report/sarif.py`** (`subscription-leak`,
`idisposable-leak`, `timer-leak`, …), чтобы майненый фикс и живая находка лежали в одних
бакетах. Сигналы заведены по экосистемам: .NET/WPF, React/TS, Android/Kotlin, Java/Spring,
плюс appendix Zig/Nim. LLM подключается **после** patch-сигналов и только на borderline
(7 ≤ score < 10), и всё равно с ручной выборкой — иначе получится «датасет, размеченный
воображением».

## 4. Сбор кандидатов — два бэкенда по масштабу

`collect.py` генерирует запросы **детерминированно** (тестируются офлайн), сам fetch
изолирован за инъектируемым HTTP-геттером (CI в сеть не ходит).

- **GitHub Search API** — норм для первого среза, но душит: ~30 req/min, hard-cap 1000
  результатов на запрос, и `language:` — это язык **репозитория**, не диффа. Поэтому язык
  диффа **обязательно** перепроверяем по changed-files (расширения из query-pack).
- **GH Archive** (`gharchive.org`, зеркало — публичный BigQuery-датасет `githubarchive`) —
  весь firehose событий. Фильтруем PR/issue по leak-ключевикам прямо в SQL, без rate-limit.
  Данные **открыты** (качай .gz и парь локально бесплатно); запрос через BigQuery требует
  GCP-аккаунта (free tier 1 TB/мес), поэтому SQL **всегда** скоупит по дневной партиции
  (`_TABLE_SUFFIX BETWEEN`) — разница между «пара центов» и «съели весь терабайт». GH
  Archive заменяет **только discovery** — патч всё равно тянется per-PR через API/clone.

Связка issue↔PR: `linked:issue` покрывает плохо — надёжнее парсить `Fixes/Closes #N` из
тела PR и GraphQL `closingIssuesReferences`. На практике начинаем **с PR**, потому что нам
нужен патч.

## 5. Доказать, что это был фикс, а не везение (ядро)

`szz.py` реализует **SZZ-критерий** (Śliwerski–Zimmermann–Zeller, 2005, *When do changes
induce fixes?*). Две ловушки, которые без него убивают корпус:

1. находка baseline-тула «исчезла после фикса» по **неправильной** причине — файл
   переехал/переименован/массово переформатирован, а не течь закрыли;
2. PR с заголовком «fix memory leak» чинит другое, а течь жива.

Защита: находка на `(file, line)` pre-fix ревизии **причинно** связана с фиксом только если
фикс-дифф **удалил или заменил эту строку**. Мы накладываем находку на removed-line-диапазоны
патча (`diffparse.touches_old_line`), поэтому «gone after» засчитывается **только** когда
это «gone *потому что изменились именно те строки*».

```
confirmed_catch = detected_before AND gone_after AND causal
```

- `detected_before` — тул пометил на pre-fix ревизии;
- `gone_after` — той же находки (tool, rule, file) нет на post-fix (по строке не матчим —
  она легально съезжает);
- `causal` — SZZ-пересечение: фикс тронул именно строку находки (с маленьким `window` под
  off-by-N; широкий `window` возвращает то самое везение).

`window` держим тесным сознательно. Для тяжёлого (трекинг переименований, отделение
рефакторинга от поведения) методически опираемся на **PyDriller + RefactoringMiner**; в коде
оставляем stdlib + `git`, чтобы CI был герметичным.

### Time-travel / lead time

`szz.lead_time(repo, leak_sha, file, line)`: от течи, которую OwnAudit пометил на старой
ревизии, идём **вперёд** по истории (`git log -L` по одной строке, фильтр по потомкам
`leak_sha`) до первого коммита, который тронул эту строку — это человеческий фикс. Отдаём
`commits_between` и дату. Маркетинговый payoff: «OwnAudit пометил бы это за N коммитов /
D дней до фикса».

## 6. Метрики — и что они честно НЕ значат

`metrics.py`, всё с оговорками:

| Метрика | Что говорит | Чем **не** является |
|---|---|---|
| `recall_on_corpus` (tool) | caught / real-fixes **в этом корпусе** | НЕ recall по «всем течам» — корпус смещён |
| `unique_to_ownaudit` | реальные фиксы, что поймал OwnAudit и не поймал ни один baseline | заголовочное число |
| `unique_miss` | реальные фиксы, что **никто** не поймал | общая слепая зона — следующий раунд работы |
| `fp_after_rate` (tool) | тул всё ещё фаерит на починенном файле | precision **smell**, не precision |
| `by_tier` | catches по тиру анализа (см. §7) | сколько ловится без сборки |
| `by_category` | распределение по таксону | — |

## 7. Тир анализа = ось зависимости от сборки (важная поправка)

Мы **статический** анализ, полная сборка проекта не нужна. Но честная граница тоньше, чем
«собирать/не собирать», поэтому каждая находка несёт `resolution`:

| Тир | Что нужно | Примеры |
|---|---|---|
| `syntactic` | сырой текст/AST, **ноль** сборки и референсов | `+=` без `-=`, `addEventListener` без `removeEventListener`, `setInterval` без `clearInterval` |
| `semantic` | разрешение символов / референс-сборки | «это *реально* `IDisposable`», «это именно event-подписка», DI lifetime |
| `interproc` | межпроцедурное ownership | retention path, XAML↔C# join — **край OwnAudit** |

Следствия:
- `by_tier` отвечает на вопрос «насколько проблема сборки вообще актуальна» — **какой %
  фиксов ловится с нулевой сборкой**. Это публикуемая цифра сама по себе.
- Сравнение «OwnAudit vs ESLint» держим **внутри тира** (ESLint без type-info — это
  `syntactic`), а суперсилу показываем отдельно на `interproc`-подвыборке. Иначе сравнение
  едет.
- Restore-гниль (старый WPF не восстановит NuGet, старый React не поставит node_modules)
  бьёт по `semantic`/`interproc`-тиру. Поэтому **build-success rate — явная метрика отбора**,
  иначе корпус схлопнется молча.

## 8. Prospective sweep — и проблема «слишком вылизанных» библиотек

`sweep.py`. Берём top-N пакетов по загрузкам, гоним OwnAudit на **текущем** HEAD, триажим,
репортим в апстрим. Acceptance rate = precision в дикой природе — смещения «только
починенное» тут нет вовсе.

Ловушка: самый верх npm/NuGet — это фундаментальные, **вылизанные донельзя** библиотеки
(Dapper, Polly, Serilog), которые *обязаны* быть без течей и дают floor-эффект. Сэмплировать
только их — узнать ничего. Поэтому отбор:

- `over_vetted_score(pkg)` — эвристика 0..1 «насколько уже вылизан»: много мейнтейнеров,
  CI, зрелый возраст, высокий stars/issue ratio, foundational-library. Это профиль
  Dapper/Polly/Serilog.
- `select_targets(..., max_vetted_fraction=0.3)` — жадно по весу отбора (загрузки,
  дисконтированные вылизанностью), но **капает долю вылизанных** и тем самым проталкивает
  application-shaped репозитории (дашборды, control-plane'ы, CLI, sample-приложения), где
  течи реально выживают.

Registry-доступ (npm downloads API, NuGet search) — за инъектируемыми геттерами, логика
отбора тестируется офлайн. Для NuGet та же схема, что для npm; query-builder'ы готовы.

## 9. MVP-объём

Не 1000 PR сразу. Phase 1: **4 экосистемы × 25 подтверждённых фиксов = 100**. И **сначала
одна** (.NET/WPF) от и до — включая before/after прогоны тулов и SZZ-привязку — потом
веер. Риск весь в сантехнике (checkout старых ревизий, разрешение референсов на
`semantic`-тире), а не в «поймаем ли течь». Zig/Nim — отдельный appendix по 10 фиксов;
Gleam пропускаем, пока не наберётся actor/process-lifecycle (и это всё равно ниша **BEAM**,
т.е. целиться надо в Elixir, а не Gleam).

## 10. CLI

```
python3 -m leakmine.cli queries  --ecosystem react_ts --merged-after 2023-01-01
python3 -m leakmine.cli sql      --ecosystem dotnet_wpf --from 20240101 --to 20241231
python3 -m leakmine.cli classify --ecosystem react_ts --patch fix.diff --title "fix leak"
python3 -m leakmine.cli confirm  --candidate cand.json --baseline eslint
python3 -m leakmine.cli metrics  --verdicts verdicts.json --baseline eslint --markdown
python3 -m leakmine.cli sweep    --packages pkgs.json --n 50 --max-vetted 0.3
python3 -m leakmine.cli leadtime --repo PATH --sha SHA --file svc.cs --line 42
```

Каждая стадия читает/пишет JSON — шаги склеиваются в shell-пайплайн; SQLite-стор —
долговременный спин для настоящего многодневного прогона.

## 11. Что это даёт практически

- реальный corpus «плохо/починено» → регрессионные тесты OwnAudit;
- приоритет правил из данных, а не из головы;
- таблица «мы vs baseline» с разбивкой по тиру;
- материал для arXiv/HN/README без позора:
  «На 100 реальных lifetime/resource-фиксах в .NET, React, Android и Java OwnAudit поймал
  Y pre-fix багов, включая Z, не пойманных baseline-линтерами; X% фиксов ловятся вообще без
  сборки».

## 12. Границы честности (повторить вслух)

- `recall_on_corpus` — по смещённому корпусу, не популяционный.
- `fp_after_rate` — smell, не precision; настоящий FP-rate требует стратифицированной
  выборки + ручной разметки (см. `audit-data-leverage.md §3`).
- «gone after» без `causal` — **не** засчитывается (это и есть антивезение).
- lead-time «исправлено по истории» ≠ «исправлено именно эту течь» на 100% — `git log -L`
  следит за строкой, не за семантикой; на сильных заявлениях подтверждать вручную.

## 13. Майнинг в CI (GitHub Action)

`.github/workflows/leakmine-mine.yml` — `leakmine mine` как self-service сборщик корпуса
на hosted-раннере. `workflow_dispatch` с инпутами (`ecosystem`, `merged_after`,
`per_query`, `min_score`) + опциональный недельный `schedule` (закомментирован). Авторизация
— штатный `GITHUB_TOKEN` (read/search публичных PR; для приватных репо или поднятия лимита
Search API — подставить PAT-секрет). На выходе артефакты: `corpus.db` (SQLite-стор),
`dataset.json` (размеченные кандидаты), `summary.md` (он же уходит в `$GITHUB_STEP_SUMMARY`).

Команда:
```
python3 -m leakmine.cli mine --ecosystem dotnet_wpf --merged-after 2024-01-01 \
  --per-query 50 --min-score 7 --sleep 2 --out-dir leakmine-out --store leakmine-out/corpus.db
```

**Что делает оркестратор** (`leakmine/mine.py`): query-pack → `fetch_search` → дедуп по
`(repo, number)` → `fetch_patch` (diff медиа-тип) → `signals.classify` → фильтр по
`min_score` → стор + dataset + summary. Сеть изолирована за инъектируемыми `search`/
`fetch_patch`, поэтому оркестрация юнит-тестится офлайн (CI наружу не ходит).

**Сознательно только discovery + classification** — это часть, которая чисто гоняется в CI.
Стадия before/after (`confirm`/`metrics`) требует checkout каждого репо и сборки анализаторов
(см. §7), поэтому остаётся локальной / self-hosted. Ограничения CI-версии: Search API
~30 req/min и cap 1000 (отсюда `--sleep` и `per_query`); одна страница на запрос (пагинация —
на потом); `language:` репо-уровневый — язык диффа всё равно перепроверяется по расширениям.

## 14. BigQuery — массовость (10k–миллионы), `leakmine/bigquery.py`

Search-API путь упирается в cap 1000, ~30 req/min и стенку per-PR fetch (~1–2k/прогон).
Для массовости backend — BigQuery. **Главное: BigQuery снимает стенку discovery, но не
стенку fetch** — GH Archive отдаёт метаданные PR (title/body/repo/number), а не дифф.
Поэтому роль BigQuery: дать огромный, уже отфильтрованный список кандидатов, который потом
узко дофетчивается и классифицируется существующим пайплайном.

### Два продукта (с РАЗНОЙ стоимостью)

**A. GH-Archive discovery (события) — `gharchive_discovery_sql`.**
SQL по `githubarchive.day.*`: merged-PR, где leak-ключевик в title ИЛИ body, нужный язык,
с отсечкой мега-PR (`changed_files <= N`, чтобы убрать «течь сбоку от рефакторинга»),
дедуп `QUALIFY ROW_NUMBER()`. **Дёшево**: скан ограничен дневными партициями (`_TABLE_SUFFIX
BETWEEN`) — сотни МБ–единицы ГБ, внутри free 1 ТБ/мес. Это и есть discovery «10k, не 10».

**B. Contents sweep (снапшот кода, zero-fetch) — `contents_sweep_sql`.**
SQL по `bigquery-public-data.github_repos`: синтаксический тир прямо в SQL — acquire без
cleanup (`addEventListener()` есть, `removeEventListener()` нет; `setInterval()` без
`clearInterval()`; и т.д., см. `SWEEP_PAIRS`). **Ноль fetch**, масштаб до миллионов файлов.
**Дорого**: любое обращение к `contents.content` сканирует весь столбец ~2.7 ТБ (~$13,
сжигает free-tier) — поэтому по умолчанию бьёт по `sample_files`/`sample_contents` (дёшево);
`--full` включай осознанно.

### Поток и замыкание петли

```text
BigQuery (SQL)  ->  экспорт NDJSON  ->  leakmine bq-ingest  ->  store + candidates.json
                                                                  |
                                          узкий per-PR fetch + signals.classify + confirm
```

`bq-ingest` принимает **только GH-Archive discovery** строки (`repo`/`number`) — на
contents-sweep строках (`repo`/`path`/`signal`) он падает с понятной ошибкой, потому что у
sweep'а нет PR-метаданных для скоринга: его экспорт сам по себе и есть набор кандидат-сайтов,
его потребляют напрямую.

`ingest_rows` грузит экспорт BigQuery в стор, **скоринг — на metadata-тире** (`metadata_score`:
ключевик в title/body + форма по размеру PR). Это **сознательно слабее** patch-классификатора:
без диффа категорию не присвоить — metadata-скор лишь ранжирует очередь на fetch. Survivors
потом дофетчиваются и проходят настоящий `signals.classify`/`confirm`.

### CLI

```bash
# A) сгенерить discovery-SQL, выполнить в BigQuery, выгрузить как NDJSON:
python3 -m leakmine.cli bq-sql --kind gharchive --ecosystem dotnet_wpf --from 20240101 --to 20241231
#   -> bq query ... | bq extract ... > rows.ndjson   (в своём GCP)

# B) загрузить результат обратно в пайплайн (metadata-тир):
python3 -m leakmine.cli bq-ingest --rows rows.ndjson --ecosystem dotnet_wpf \
        --min-meta-score 4 --out-dir bq-out --store bq-out/corpus.db

# zero-fetch syntactic sweep по снапшоту кода (по умолчанию дешёвый sample_*):
python3 -m leakmine.cli bq-sql --kind contents --ecosystem react_ts          # --full = весь ~2.7TB
```

### Стоимость и честность
- discovery (A): партиция-скоуп обязателен; без него скан = вся история (терабайты).
- contents (B): `content` — не партиционирован, фильтры скан не уменьшают → `sample_*` по
  умолчанию; полный скан только когда реально надо и бюджет позволяет.
- metadata-скор ≠ patch-классификация: BigQuery даёт чистую *очередь*, не финальный вердикт.
- стенка fetch остаётся: на 100k+ дофетч диффов делается клонированием репо (`--filter=blob:none`,
  `git show`) вне Actions, либо для проспективного sweep'а полагаемся на contents-тир (без fetch).
