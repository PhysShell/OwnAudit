# Building the STS stand for collector runs

How to (re)produce the environment the step-7 acceptance ran on
(`docs/collector-plan.md`): a **shipping** build of STS plus the SerializerSim harness
that deserializes real documents and holds for the ClrMD collector. Written for the next
agent/session; every path below is a placeholder — resolve them on the machine
(`<STS_new>` = the STS git checkout, `<broker>` = the serializer-research folder with
`src/SerializerSim`, `<OwnAudit>` = this repo).

## 1. Which binaries you need — and why it matters

The harness reflects over `Setup\*.dll`. Two states exist:

- `<STS_new>\Setup` — whatever was last built there (a feature-branch build, e.g.
  `dsector_optimization`, may require the full catalogs/dictionary bootstrap in document
  ctors — under the lightweight harness bootstrap those throw «Не найден справочник N»
  and every document is skipped).
- **A shipping build** (`develop`/`master`) — document ctors work with the harness's
  minimal AppData bootstrap. This is what the leak ground truth (`broker/runner/LEAK.md`)
  and the acceptance used.

So: don't fight the feature-branch Setup — build shipping into a **separate worktree**.

## 2. Build the shipping Setup (a few minutes)

```powershell
# 1. worktree at the shipping commit (pin by date if develop has moved on):
git -C <STS_new> rev-list -1 --before="<date>" develop     # pick the commit
git -C <STS_new> worktree add <STS_shipping> <commit>

# 2. old-style csproj HintPaths expect ..\..\packages — copy them in:
robocopy <STS_new>\packages <STS_shipping>\packages /E /NFL /NDL /NJH /NJS /NP

# 3. build; the solution outputs STRAIGHT INTO <STS_shipping>\Setup:
&"...\2022\BuildTools\MSBuild\Current\Bin\MSBuild.exe" <STS_shipping>\Broker.sln `
    /restore /p:Configuration=Release /m /v:m
```

Notes:
- `Setup/` is **gitignored build output** — the solution's project OutDirs point at it;
  nothing else populates it. Rebuilding it is always safe in a worktree.
- Templates\ and FLK.dll land in Setup as part of the build; the harness AppDomain is
  based at Setup so it finds them.
- Catalogs images live at `%ProgramData%\sector.kz\Catalogs` (NOT `Sector\Catalogs`) —
  the shipping build does not need them under the harness bootstrap, feature branches do.

## 3. Build the harness

`<broker>\build.ps1` compiles `src/SerializerSim` with csc against `Setup\Core.dll`
(net472, x64). For a debug build with PDB line numbers add `/debug:full` and a distinct
`/out:` (see the script — it is a plain csc invocation). Two harness facts added for the
collector work:

- **`SERIALIZERSIM_SETUP`** env var overrides the pinned Setup path — point it at
  `<STS_shipping>\Setup` and the same exe runs against the shipping binaries.
- **`leaktest --hold`** prints `SCENARIO-READY` after the leaky/fixed passes and blocks
  on stdin — that is the collector attach point. The leaky pass's survivors stay pinned
  by `AppData.Properties`; the fixed pass is the built-in FP control.

```powershell
$env:SERIALIZERSIM_SETUP = "<STS_shipping>\Setup"
cd <broker>
.\bin\SerializerSimDbg.exe leaktest --limit 60 --tables GTD,KDT --hold
# tables: GTD,KDT[,PGC]; DBs default broker_ts_electrovoz on the SERVER const in Program.cs
```

## 4. Collect + correlate

While the harness holds (`SCENARIO-READY` printed):

```powershell
cd <OwnAudit>
dotnet run --project src/OwnAudit.Cli -- collect --pid <harness pid> `
    --findings sts_audit/findings.json --max-chains 40 `
    --scenario "<label>" --iterations <docs> --out artifacts/runtime-sts.json
# release the hold: write a line to the harness stdin, or just stop the process
python3 -m runtime.cli --findings sts_audit/findings.json --runtime artifacts/runtime-sts.json
```

`--max-chains 40` matters: the harness's own prototype/parents statics are legitimate
nearest roots, so with few samples the event chains (`GBProperty.PropertyChanged`) may
not appear among them.

## 5. Known traps

| Trap | Symptom | Fix |
|---|---|---|
| Feature-branch Setup | «Не найден справочник N» in ctors, all documents skipped | build shipping into a worktree (§2) |
| Missing packages in worktree | CS0246 XLWorkbook/Ionic | copy `packages\` (§2.2) |
| `python`/`py` not on Windows PATH | tests/correlate fail to start | WSL NixOS: `nix-shell -p python3 --run '…'` (repo `flake.nix` currently has a syntax error — don't rely on `nix develop`) |
| Attach shows 0 documents | ctors threw; heap really is empty | check the harness output for the skip counter |
| Fixed exe doesn't leak | current `SerializerSim.exe` detaches by design | use `leaktest` (its no-detach pass leaks deliberately) — the old `SerializerSim.baseline.exe` needs the old Setup anyway |
