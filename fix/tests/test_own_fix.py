"""T4 OWN001/OWN014 fixer tests (docs/fix-arm.md §5). Bare python3 or pytest:

    PYTHONPATH=fix python3 fix/tests/test_own_fix.py

Drives the real OWN fixer (it actually rewrites the source — not a replay) through
the same wrapper as every other applier, so the safety contract is exercised too.
"""
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "fix"))

from fixarm import tiers                                              # noqa: E402
from fixarm.appliers import ReplayReaudit                            # noqa: E402
from fixarm.own_fix import (                                         # noqa: E402
    OwnFixApplier, classify, plan_file,
    NAMED_HANDLER_SUB, INLINE_LAMBDA_SUB, DISPOSABLE_FIELD, DISPOSABLE_LOCAL,
)
from fixarm.orchestrate import (                                     # noqa: E402
    Finding, load_findings, run_fix, OK, REJECTED,
)

FIX = os.path.join(ROOT, "fix", "fixtures")


def _seed(fixture: str) -> str:
    d = tempfile.mkdtemp(prefix="ownfix-")
    src = os.path.join(FIX, fixture, "before")
    for dp, _, names in os.walk(src):
        for n in names:
            full = os.path.join(dp, n)
            dst = os.path.join(d, os.path.relpath(full, src))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(full, dst)
    return d


@contextmanager
def _wrapped(fixture: str, rule: str):
    fdir = os.path.join(FIX, fixture)
    before = load_findings(os.path.join(fdir, "before.findings.json"))
    wd = _seed(fixture)
    try:
        applier = OwnFixApplier([f for f in before if f.rule == rule])
        yield run_fix(
            before=before, workdir=wd, rule=rule, applier=applier,
            reaudit=ReplayReaudit(os.path.join(fdir, "after.findings.json")),
        ), wd, applier
    finally:
        shutil.rmtree(wd, ignore_errors=True)


def _read(wd: str, rel: str) -> list[str]:
    with open(os.path.join(wd, rel), encoding="utf-8") as fh:
        return fh.readlines()


def _expect(actual, expected, what="value"):
    """`-O`-safe equality check — `assert` is stripped under python -O, so exit-code
    checks must raise explicitly."""
    if actual != expected:
        raise AssertionError(f"{what}: expected {expected!r}, got {actual!r}")


# ---- classifier: the honesty boundary --------------------------------------

def test_classify_named_vs_lambda():
    named = "event 'fGoods.PropertyChanged' is subscribed (handler 'new PropertyChangedEventHandler(GoodsPropertyChanged)')"
    lam = "event 'stage.PropertyChanged' is subscribed (handler '(s2, e2) => OnPropertyChanged(\"Stages\")') ... inline lambda"
    assert classify(named)[0] == NAMED_HANDLER_SUB
    assert classify(named)[1:] == ("fGoods.PropertyChanged", "new PropertyChangedEventHandler(GoodsPropertyChanged)")
    assert classify(lam)[0] == INLINE_LAMBDA_SUB
    field = "IDisposable field '_timer' (type 'Timer') is never disposed — its owner 'ShareWindow' leaks it"
    local = "IDisposable local 'MyProc' is never disposed (leak)"
    assert classify(field)[0] == DISPOSABLE_FIELD and classify(field)[1] == "_timer"
    assert classify(local)[0] == DISPOSABLE_LOCAL    # suggest-only


# ---- OWN001 named handler on a Window -> Closed teardown -------------------

def test_own001_window_inserts_closed_detach():
    rel = "Broker/AmountWindow.xaml.cs"
    before = _read(_seed("own001-sub-window"), rel)   # length reference
    with _wrapped("own001-sub-window", "OWN001") as (res, wd, _applier):
        assert res.status == OK, res.ledger()
        assert res.tier == tiers.T4 and res.gate == tiers.REVIEW   # never auto
        assert not res.committable
        lines = _read(wd, rel)
        assert len(lines) == len(before) + 1            # exactly one line added
        sub = next(i for i, line in enumerate(lines) if "fGoods.PropertyChanged +=" in line)
        # the detach is inserted immediately after the subscription, in a Closed hook
        assert lines[sub + 1].strip() == (
            "this.Closed += (s, e) => fGoods.PropertyChanged -= "
            "new PropertyChangedEventHandler(GoodsPropertyChanged);")
        assert lines[sub].startswith("            ") and lines[sub + 1].startswith("            ")


# ---- OWN014 region-escape on a UserControl -> Unloaded teardown ------------

def test_own014_usercontrol_inserts_unloaded_detach():
    rel = "Broker/KTS/KTSGoods2.xaml.cs"
    with _wrapped("own014-region-escape", "OWN014") as (res, wd, _applier):
        assert res.status == OK, res.ledger()
        assert res.tier == tiers.T4
        lines = _read(wd, rel)
        sub = next(i for i, line in enumerate(lines) if "fThis.PropertyChanged +=" in line)
        assert lines[sub + 1].strip() == (
            "this.Unloaded += (s, e) => fThis.PropertyChanged -= data_PropertyChanged;")


# ---- OWN001 subscription folds into an existing OnClosed override -----------

def test_own001_subscription_folds_into_onclosed():
    rel = "Broker/FoldWindow.xaml.cs"
    fdir = os.path.join(FIX, "own001-sub-fold")
    before = load_findings(os.path.join(fdir, "before.findings.json"))
    wd = _seed("own001-sub-fold")
    try:
        new, applied, skipped = plan_file(os.path.join(wd, rel), before)
        assert [d for _, d in applied] == ["Closed/fold"], (applied, skipped)   # fold, not plain Closed
        lines = new.splitlines(keepends=True)
        oc = next(i for i, line in enumerate(lines) if "override void OnClosed" in line)
        assert lines[oc + 1].strip() == "{"
        assert lines[oc + 2].strip() == (
            "fGoods.PropertyChanged -= new PropertyChangedEventHandler(GoodsPropertyChanged);")
        assert "this.Closed += (s, e) =>" not in new                            # no stacked lambda
    finally:
        shutil.rmtree(wd, ignore_errors=True)


def test_fold_skips_ctor_local_source():
    # source `goods` is a ctor parameter (not a member) -> folding the raw detach into
    # OnClosed would be out of scope; must keep the capturing lambda at the call site.
    src = ("public partial class W : Window\n"
           "{\n"
           "    public W(Goods goods)\n"
           "    {\n"
           "        InitializeComponent();\n"
           "        goods.PropertyChanged += new PropertyChangedEventHandler(H);\n"
           "    }\n"
           "    protected override void OnClosed(EventArgs e)\n"
           "    {\n"
           "        base.OnClosed(e);\n"
           "    }\n"
           "    private void H(object s, PropertyChangedEventArgs e) { }\n"
           "}\n")
    d, path = _tmp_cs(src)
    try:
        f = Finding("OWN001", "W.cs", 6, tool="own-check",
                    message="event 'goods.PropertyChanged' is subscribed (handler 'new PropertyChangedEventHandler(H)') ...")
        new, applied, skipped = plan_file(path, [f])
        assert [d for _, d in applied] == ["Closed"], (applied, skipped)        # lambda, not fold
        assert "this.Closed += (s, e) => goods.PropertyChanged -= new PropertyChangedEventHandler(H);" in new
        # OnClosed body must be untouched (no out-of-scope detach folded in)
        assert "goods.PropertyChanged -=" in new and new.count("goods.PropertyChanged -=") == 1
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_fold_ignores_nested_type_onclosed():
    # the field's class has no OnClosed; a NESTED type does. Must not fold into it.
    src = ("public partial class Outer : Window\n"
           "{\n"
           "    private readonly Timer _t;\n"
           "    public Outer()\n"
           "    {\n"
           "        InitializeComponent();\n"
           "    }\n"
           "    private class Inner\n"
           "    {\n"
           "        protected override void OnClosed(EventArgs e) { }\n"
           "    }\n"
           "}\n")
    d, path = _tmp_cs(src)
    try:
        f = Finding("OWN001", "Outer.cs", 3, tool="own-check",
                    message="IDisposable field '_t' (type 'Timer') is never disposed — its owner 'Outer' leaks it")
        new, applied, skipped = plan_file(path, [f])
        assert [d for _, d in applied] == ["Closed"], (applied, skipped)        # lambda, not folded into Inner
        assert "this.Closed += (s, e) => _t?.Dispose();" in new
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---- OWN001 disposable field on a Window -> dispose on Closed ---------------

def test_own001_disposable_field_disposes_on_closed():
    rel = "Broker/ShareWindow.xaml.cs"
    before = _read(_seed("own001-disposable-field"), rel)
    with _wrapped("own001-disposable-field", "OWN001") as (res, wd, _applier):
        assert res.status == OK, res.ledger()
        assert res.tier == tiers.T4 and res.gate == tiers.REVIEW
        lines = _read(wd, rel)
        assert len(lines) == len(before) + 1
        # the dispose hook is anchored right after InitializeComponent(), in a Closed hook
        init = next(i for i, line in enumerate(lines) if "InitializeComponent()" in line)
        assert lines[init + 1].strip() == "this.Closed += (s, e) => _timer?.Dispose();"


# ---- OWN001 disposable local -> block `using` wrap -------------------------

def test_own001_disposable_local_wraps_in_using():
    rel = "Broker/Helper.cs"
    with _wrapped("own001-disposable-local", "OWN001") as (res, wd, _applier):
        assert res.status == OK, res.ledger()
        text = "".join(_read(wd, rel))
        assert "using (var myProcess = new Process())" in text     # wrapped
        assert "var myProcess = new Process();" not in text        # bare decl gone
        # the using opener is immediately followed by its block brace
        lines = _read(wd, rel)
        u = next(i for i, line in enumerate(lines) if "using (var myProcess" in line)
        assert lines[u + 1].strip() == "{"


# ---- OWN001 inline lambda -> extract to a named handler + detach ------------

def test_own001_inline_lambda_extracted_and_detached():
    rel = "Broker/DatabaseOptimizationWindow.xaml.cs"
    with _wrapped("own001-lambda-extract", "OWN001") as (res, wd, _applier):
        assert res.status == OK, res.ledger()
        assert res.tier == tiers.T4
        text = "".join(_read(wd, rel))
        assert "stage.PropertyChanged += OnStagePropertyChanged;" in text          # method group
        assert "this.Closed += (s, e) => stage.PropertyChanged -= OnStagePropertyChanged;" in text
        assert ('private void OnStagePropertyChanged(object s2, '
                'System.ComponentModel.PropertyChangedEventArgs e2) '
                '=> OnPropertyChanged("Stages");') in text                          # extracted, qualified args
        assert "+= (s2, e2) =>" not in text                                        # the lambda is gone


# ---- refused shapes stay suggest-only: NOT patched -------------------------

def test_lambda_extraction_more_delegates():
    # both newly-added INotify-family events are unambiguous -> extractable with the
    # right (fully-qualified) args type.
    cases = [
        ("PropertyChanging", "System.ComponentModel.PropertyChangingEventArgs", "OnMPropertyChanging"),
        ("ErrorsChanged", "System.ComponentModel.DataErrorsChangedEventArgs", "OnMErrorsChanged"),
    ]
    for ev, args_type, method in cases:
        src = ("public partial class W : Window\n"
               "{\n"
               "    public W(Model m)\n"
               "    {\n"
               "        InitializeComponent();\n"
               f"        m.{ev} += (s, e) => Refresh();\n"
               "    }\n"
               "    private void Refresh() { }\n"
               "}\n")
        d, path = _tmp_cs(src)
        try:
            f = Finding("OWN001", "W.cs", 6, tool="own-check",
                        message=f"event 'm.{ev}' is subscribed (handler '(s, e) => Refresh()') ...")
            new, applied, skipped = plan_file(path, [f])
            assert [dt for _, dt in applied] == ["extract+detach"], (ev, skipped)
            assert f"m.{ev} += {method};" in new
            assert f"private void {method}(object s, {args_type} e) => Refresh();" in new
        finally:
            shutil.rmtree(d, ignore_errors=True)


def test_block_lambda_is_not_patched():
    # a block-body lambda can't be a clean expression method -> suggest-only, untouched
    rel = "Broker/DatabaseOptimizationWindow.xaml.cs"
    fdir = os.path.join(FIX, "own001-lambda")
    before = load_findings(os.path.join(fdir, "before.findings.json"))
    wd = _seed("own001-lambda")
    try:
        applier = OwnFixApplier(before)
        original = _read(wd, rel)
        applier.apply(wd, "OWN001")
        assert _read(wd, rel) == original                # tree untouched
        assert [r for _, r in applier.skipped] == ["lambda-shape-unsupported"]
    finally:
        shutil.rmtree(wd, ignore_errors=True)


def test_local_passed_to_call_is_not_wrapped():
    # local handed to a retaining API (Add) may be kept alive -> refuse, no use-after-dispose
    src = ("public static class H\n"
           "{\n"
           "    public static void Run()\n"
           "    {\n"
           "        var p = new Process();\n"
           "        sink.Add(p);\n"
           "    }\n"
           "}\n")
    d, path = _tmp_cs(src)
    try:
        f = Finding("OWN001", "H.cs", 5, tool="own-check",
                    message="IDisposable local 'p' is never disposed (leak)")
        new, applied, skipped = plan_file(path, [f])
        assert new == src and applied == []
        assert [r for _, r in skipped] == ["local-escapes"]
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_local_captured_by_lambda_is_not_wrapped():
    # local captured by a closure that may outlive the block -> refuse
    src = ("public partial class W : Window\n"
           "{\n"
           "    public void Run()\n"
           "    {\n"
           "        var p = new Process();\n"
           "        button.Click += (s, e) => p.Start();\n"
           "    }\n"
           "}\n")
    d, path = _tmp_cs(src)
    try:
        f = Finding("OWN001", "W.cs", 5, tool="own-check",
                    message="IDisposable local 'p' is never disposed (leak)")
        new, applied, skipped = plan_file(path, [f])
        assert new == src and applied == []
        assert [r for _, r in skipped] == ["local-escapes"]
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_ctor_anchor_bounded_to_enclosing_class():
    # the field's class has no InitializeComponent(); a LATER class does. The hook
    # must NOT be anchored in the wrong class -> suggest-only (no-ctor-anchor).
    src = ("public class A\n"
           "{\n"
           "    private readonly Timer _t;\n"
           "}\n"
           "public partial class B : Window\n"
           "{\n"
           "    public B() { InitializeComponent(); }\n"
           "}\n")
    d, path = _tmp_cs(src)
    try:
        f = Finding("OWN001", "A.cs", 3, tool="own-check",
                    message="IDisposable field '_t' (type 'Timer') is never disposed — its owner 'A' leaks it")
        new, applied, skipped = plan_file(path, [f])
        assert new == src and applied == []
        assert [r for _, r in skipped] == ["no-ctor-anchor"]
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_multiple_disposable_fields_all_disposed():
    # two fields anchored after the same InitializeComponent() must BOTH get a hook
    src = ("public partial class W : Window\n"
           "{\n"
           "    private readonly Timer _t1;\n"
           "    private readonly Timer _t2;\n"
           "    public W()\n"
           "    {\n"
           "        InitializeComponent();\n"
           "    }\n"
           "}\n")
    d, path = _tmp_cs(src)
    try:
        msg = "IDisposable field '{}' (type 'Timer') is never disposed — its owner 'W' leaks it"
        fs = [Finding("OWN001", "W.cs", 3, tool="own-check", message=msg.format("_t1")),
              Finding("OWN001", "W.cs", 4, tool="own-check", message=msg.format("_t2"))]
        new, applied, skipped = plan_file(path, fs)
        assert len(applied) == 2 and skipped == []           # neither skipped as overlap
        assert new.count("this.Closed += (s, e) => _t1?.Dispose();") == 1
        assert new.count("this.Closed += (s, e) => _t2?.Dispose();") == 1
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_escaping_local_is_not_wrapped():
    # a local that is returned must NOT be wrapped (would dispose before use)
    src = ("public static class H\n"
           "{\n"
           "    public static Process Make()\n"
           "    {\n"
           "        var p = new Process();\n"
           "        return p;\n"
           "    }\n"
           "}\n")
    d, path = _tmp_cs(src)
    try:
        f = Finding("OWN001", "H.cs", 5, tool="own-check",
                    message="IDisposable local 'p' is never disposed (leak)")
        new, applied, skipped = plan_file(path, [f])
        assert new == src and applied == []
        assert [r for _, r in skipped] == ["local-escapes"]
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---- the fixer's own revert: a rejected OWN fix rolls back -----------------

def test_own_fix_reverts_on_regression():
    fdir = os.path.join(FIX, "own001-sub-window")
    rel = "Broker/AmountWindow.xaml.cs"
    before = load_findings(os.path.join(fdir, "before.findings.json"))
    wd = _seed("own001-sub-window")
    original = _read(wd, rel)
    try:
        applier = OwnFixApplier(before)
        # re-audit pretends the detach introduced a brand-new finding -> must reject + revert
        regress = [Finding("CS0103", rel, 15, tool="roslyn", message="name 's' does not exist")]
        res = run_fix(before=before, workdir=wd, rule="OWN001",
                      applier=applier, reaudit=lambda _wd: regress)
        assert res.status == REJECTED, res.ledger()
        assert res.reverted
        assert _read(wd, rel) == original                # detach rolled back out
    finally:
        shutil.rmtree(wd, ignore_errors=True)


# ---- review hardening: unbraced guards, dedup, path safety, CLI ------------

def _tmp_cs(src: str):
    d = tempfile.mkdtemp(prefix="ownfix-")
    p = os.path.join(d, "W.cs")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(src)
    return d, p


def test_unbraced_if_guard_is_skipped():
    # subscription is the single statement of an unbraced `if` -> suggest-only
    src = ("public partial class W : Window\n"
           "{\n"
           "    public W(Goods g)\n"
           "    {\n"
           "        if (g != null)\n"
           "            g.PropertyChanged += new PropertyChangedEventHandler(H);\n"
           "    }\n"
           "}\n")
    d, p = _tmp_cs(src)
    try:
        f = Finding("OWN001", "W.cs", 6, tool="own-check",
                    message="event 'g.PropertyChanged' is subscribed (handler 'new PropertyChangedEventHandler(H)')")
        new, applied, skipped = plan_file(p, [f])
        assert new == src and applied == []           # tree untouched
        assert skipped and skipped[0][1] == "unbraced-control-flow"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_duplicate_findings_one_insert():
    src = ("public partial class W : Window\n"
           "{\n"
           "    public W(Goods g)\n"
           "    {\n"
           "        g.PropertyChanged += new PropertyChangedEventHandler(H);\n"
           "    }\n"
           "}\n")
    d, p = _tmp_cs(src)
    try:
        msg = "event 'g.PropertyChanged' is subscribed (handler 'new PropertyChangedEventHandler(H)')"
        dupes = [Finding("OWN001", "W.cs", 5, tool="own-check", message=msg),
                 Finding("OWN001", "W.cs", 5, tool="own-check", message=msg)]
        new, applied, skipped = plan_file(p, dupes)
        assert new.count("this.Closed +=") == 1       # one detach, not two
        assert len(applied) == 1
        assert [r for _, r in skipped] == ["duplicate-site"]   # the dupe is in the ledger, not dropped
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_path_traversal_is_rejected():
    wd = _seed("own001-sub-window")
    try:
        for bad in ("../escape.cs", "/etc/passwd"):
            applier = OwnFixApplier([Finding("OWN001", bad, 1, tool="own-check",
                                             message="event 'a.E' is subscribed (handler 'H')")])
            try:
                applier.apply(wd, "OWN001")
                raise AssertionError(f"expected ValueError for {bad!r}")  # not `assert` (stripped under -O)
            except ValueError:
                pass
    finally:
        shutil.rmtree(wd, ignore_errors=True)


def test_cli_replay_on_own_fixture_fails_fast():
    from fixarm.cli import main
    rc = main(["--fixture", os.path.join(FIX, "own001-sub-window"),
               "--rule", "OWN001", "--applier", "replay"])
    _expect(rc, 2, "replay on after-less fixture")     # refuse, don't delete


def test_cli_defaults_own_rule_to_own_applier():
    from fixarm.cli import main
    rc = main(["--fixture", os.path.join(FIX, "own001-sub-window"), "--rule", "OWN001"])
    _expect(rc, 0, "OWN* auto-routes to own fixer")


def test_cli_no_op_does_not_need_after_findings():
    # own001-lambda has no after.findings.json; a no-op rule returns before re-audit,
    # so the missing file must NOT be treated as an error (deferred check).
    from fixarm.cli import main
    rc = main(["--fixture", os.path.join(FIX, "own001-lambda"), "--rule", "RCS9999",
               "--applier", "own"])
    _expect(rc, 0, "no-op, re-audit never reached")


def test_cli_missing_after_findings_fails_cleanly_when_reaudit_needed():
    # Same fixture, but a fixable rule -> re-audit IS reached -> clean exit 2, not a stacktrace.
    from fixarm.cli import main
    rc = main(["--fixture", os.path.join(FIX, "own001-lambda"), "--rule", "OWN001",
               "--applier", "own"])
    _expect(rc, 2, "reaudit needed but after.findings.json missing")


# ---- bare-python runner ----------------------------------------------------

def _main() -> int:
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
