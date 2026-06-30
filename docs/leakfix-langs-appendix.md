# Appendix — «новомодные» языки как ниша для Own*

Спутник к `docs/leakfix-mine.md`. Тот документ описывает **методику** добычи leak-fix
корпуса; этот — **где** её имеет смысл применять за пределами .NET/TS/Android, и насколько
каждый язык — настоящая боль, а насколько просто «блестящая пуговица на куртке программиста».

Вывод вперёд: Zig/Odin/Nim/Gleam интересны, но как **золотая ниша** слабее, чем .NET/XAML и
TS/React — там либо рынок меньше, либо сама модель языка уже снижает именно тот класс боли,
который Own* ловит. Это research-материал и доказательство переносимости OwnIR, а не первый
коммерческий рынок.

Каждый язык ниже снабжён рабочим query-pack'ом в `leakmine/signals.py` (`ZIG`, `NIM`, `ODIN`
— ecosystem + `LANGS`), так что mining по ним запускается тем же пайплайном, что и основные
экосистемы (маленькой выборкой — «proof of portability»).

---

## Zig

Самый близкий к Own*-идее. GC нет, память — явно через allocators, `defer`/`errdefer`,
ownership-конвенции и документация API. Официальная дока прямо говорит: программист отвечает
за то, чтобы pointer не использовался после освобождения; если функция возвращает pointer —
дока обязана объяснить, кто им владеет и кто `free`'ит; lifetime слайса может зависеть от
resize контейнера. Это буквально пахнет OwnIR. Плюс `std.testing.allocator` репортит leak'и в
тестах (забытый `deinit` → leak report), а `defer`/`errdefer` — уже явный cleanup-механизм
(`defer` на выходе из scope, `errdefer` — только на error-пути).

**Ниша OwnZig:**
- функция возвращает память, owned by caller, а caller не освобождает;
- allocator передан в функцию, но парного `free`/`deinit` нет;
- `errdefer` забыт на error-пути после частичного acquire;
- слайс живёт дольше resize/realloc контейнера;
- API-доки говорят «caller owns», а код контракт не соблюдает;
- arena / general-purpose allocator lifetime mismatch.

**Минусы:** комьюнити меньше .NET/JS/JVM; Zig-разработчики уже думают про allocator/defer;
`std.testing.allocator` частично закрывает runtime-детект; нужно очень хорошо знать ownership-
конвенции Zig.

**Вердикт:** отличный research spike и материал для статьи, не лучший первый коммерческий
рынок. «OwnZig: static allocator/lifetime contract checker» — да, но позже.

## Odin

Стоит ближе к Zig/C, чем к Rust/Go/C#: GC по умолчанию нет, ручное управление памятью,
allocator-first модель, `defer` для cleanup, **implicit `context`** с allocator/log/temp-
allocator, data-oriented стиль. Управление в основном ручное (нет tracing GC), `defer`
гарантирует cleanup в конце scope:

```odin
data := make([]int, 1024)
defer delete(data)
```

Главная фишка — allocator через `context`: implicit context неявно передаётся в вызовы и
задаёт, например, какой allocator использует сторонний код. Для анализа это рождает вопросы:
из какого allocator пришла память? каким её надо освободить? не ушла ли память из temp-
allocator наружу? не смешали ли temp и persistent storage? Именно поэтому Odin для Own*-идеи
интереснее Zig в одном месте — **анализ не просто «забыли free», а lifetime/context**:

```
{ "resource": "allocation", "allocator": "context.allocator",
  "acquire": "make([]T)", "release": "delete(x)", "scope": "current procedure" }
```

**Где Odin течёт (предлагаемые правила):**

| Правило | Класс |
|---|---|
| `ODIN001` | allocation создана через `context.allocator`, но не `delete` на всех выходах |
| `ODIN002` | cleanup не отложен сразу (`prefer defer delete` рядом с acquire) — style/safety |
| `ODIN003` | allocator mismatch: выделено A, освобождено B |
| `ODIN014` | значение из **temporary allocator** уезжает за пределы его scope (temp escape) |
| `ODIN020` | slice/view переживает backing-контейнер |
| `ODIN021` | контейнер удалён, пока view ещё используется |

`ODIN014` — самый вкусный: это почти `OWN014`, только вместо WPF publisher/subscriber —
`allocation lifetime < returned value lifetime`:

```odin
make_name :: proc() -> string {
    context.allocator = temp_allocator()
    s := strings.clone("hello")
    return s        // строка из temp allocator уехала наружу
}
```

**MVP** можно начать не полноценным компиляторным frontend'ом, а tree-sitter/regex+AST
гибридом: ловить `make`/`new`/`alloc`, `delete`/`free`/`destroy`, `defer delete`,
`context.allocator` assignment, return allocated value, field assignment of allocated value.

**Оценка:** technical fit 8/10, market 3/10, competition 2/10, research 8/10, first-product
priority 4/10. Отличный proof-of-portability spike, но не первый рынок.

## Nim

Интересен несколькими режимами памяти. Рекомендованный для нового кода — `--mm:orc` (default,
reference counting + cycle collector); `--mm:arc` похож, но без cycle collector — и дефолтный
async под ARC создаёт циклы и течёт, поэтому для async нужен ORC. Исследовательски вкусно:

```
ARC:   cycles leak
ORC:   cycles collected
async: can create cycles under ARC
move:  compiler optimizes RC ops
```

**Ниша OwnNim:** reference cycles под ARC; async/task/callback циклы; случайно удержанный
ref-object граф; контракты destructor/finalizer/resource; mode-sensitive диагностика
(`--mm:arc` vs `--mm:orc`).

**Минусы:** рынок маленький; у Nim уже compiler-level MM-семантика; большая часть «GC leak»
боли зависит от выбранного `--mm`; пользователей мало.

**Вердикт:** круто для академического appendix'а, не «золотая ниша». Добавить в mining
маленькой выборкой — показать, что OwnIR переносится на RC/ORC мир.

## Gleam

Компилируется в Erlang или JavaScript, статически типизирован, GC, immutable data,
BEAM/actor-модель. Для классических Own.NET-болей слабее: immutable data убирает shared
mutable object graph hell; BEAM-процессы изолированы; нет WPF-style `event +=`, удерживающего
ViewModel; нет IDisposable hell в C#-смысле.

**Но другие leak-подобные проблемы есть:** процессы не завершаются; растёт mailbox;
timers/process monitors/subscriptions не снимаются; long-lived actor держит state; JS-target
наследует JS/DOM cleanup-проблемы.

**Вердикт:** не золотая ниша для Own*. Там нужен не ownership checker, а
actor/lifecycle/mailbox/process-resource audit — другой зверь. И это всё равно ниша **BEAM**,
т.е. целиться надо в Elixir, а не Gleam. В mining пропускаем, пока не наберётся достаточно
actor/process-lifecycle фиксов.

---

## OwnSys — общая рамка для systems-языков

Zig и Odin логично объединить в одну исследовательскую категорию:

> **OwnSys** — allocator-aware lifetime/resource checker для Zig/Odin/C-подобных современных
> системных языков.

Одно ядро OwnIR представляет и `acquire`/`release`/`borrow`(view)/`escape`/`lifetime region`/
`allocator-context` — разница только во frontend-фактах:

```
Один OwnIR-модель описывает:
  WPF event retention      (.NET)
  React effect cleanup     (TS)
  Odin allocator escape    (systems)
  Zig defer/delete discipline (systems)
```

Эта фраза — уже «platform-agnostic core», а не «мы накидали всего в README».

## Итоговая карта приоритетов

```
1. .NET/WPF/XAML/DI   — первый продукт, реальная боль, наш максимум
2. TS/React           — пиарный spike, огромный рынок
3. Android/Kotlin     — сильная lifecycle-боль, но конкуренция в tooling
4. Zig/Odin (OwnSys)  — systems proof-of-portability, allocator/lifetime contracts
5. Java/Spring        — enterprise resource/lifetime контракты
6. Nim                — ARC/ORC/cycles niche
7. Gleam              — actor/process lifecycle, не классический Own*
```

По technical fit Zig/Odin — самые «идеологически родные», но рынок и боль у .NET/React проще
конвертировать в adoption. Маркетинг важнее красоты модели — живём не в proof assistant.

| Язык | technical fit | рынок | конкуренция | research | first-product |
|---|---:|---:|---:|---:|---:|
| Zig | высокий | малый/средний | низкая | высокая | низкий |
| Odin | 8/10 | 3/10 | 2/10 | 8/10 | 4/10 |
| Nim | средний | малый | низкая | средняя | низкий |
| Gleam | низкий* | малый | — | средняя | низкий |

\* для классического Own*; для actor/process-lifecycle — отдельная история (BEAM/Elixir).

---

*Источник: собственный анализ автора проекта (рыночно-нишевая оценка Zig/Nim/Gleam/Odin +
рамка OwnSys). Query-паки и сигналы для Zig/Nim/Odin живут в `leakmine/signals.py`; methodology
mining — в `docs/leakfix-mine.md`.*
