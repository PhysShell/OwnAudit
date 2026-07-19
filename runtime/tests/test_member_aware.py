"""Member-aware static-event correlation (the collector-plan step-7 follow-up, closed).

A subscription-leak finding whose message names the event in the canonical own-check
form (event 'A.B.Holder.Member') must confirm ONLY against a static-event root with the
same (short holder, member) key. Type identity alone no longer transfers a runtime root
onto unrelated event findings of the same class — the exact failure the STS acceptance
exposed (GTD confirmed via GTD.cs:2466 while the real 5192 site was unflagged).

Bare python3: PYTHONPATH=. python3 runtime/tests/test_member_aware.py   (-O-safe)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from runtime import correlate as C                                        # noqa: E402

CFG = {"leak_categories": ["subscription-leak", "idisposable-leak", "region-escape"],
       "default_expected": 1, "min_count": 2, "high_count": 10}


def _expect(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _sf(path, line, event_expr, cat="subscription-leak", rule="OWN001"):
    msg = ("event '%s' is subscribed (handler 'H') but never unsubscribed; may keep the "
           "instance alive [resource: subscription token]" % event_expr) if event_expr else \
          "no matching unsubscribe"
    return {"tool": "own-check", "rule": rule, "category_name": cat,
            "resource": "subscription token", "path": path, "line": line,
            "message": msg, "suppressed": False}


def _rec(t, count, roots, expected=0):
    return {"type": t, "count": count, "expected": expected, "roots": roots}


def _ev_root(holder, member):
    return {"kind": "static-event", "holder": holder, "member": member, "via": "delegate"}


def _dump(*records):
    return {"schema": "ownAudit/runtime/v1", "scenario": "s", "iterations": 10,
            "retained": list(records)}


def test_two_events_only_the_matching_one_confirms():
    static = [_sf("B/Doc.cs", 100, "AppData.Properties.GBProperty.PropertyChanged"),
              _sf("B/Doc.cs", 200, "Regime.PropertyChanged")]
    dump = _dump(_rec("Ns.Doc", 50, [_ev_root("Ns.Property.GBProperty", "PropertyChanged")]))
    res = C.correlate(static, dump, CFG)
    _expect(len(res["confirmed"]) == 1, res)
    _expect(res["confirmed"][0]["line"] == 100, res["confirmed"])
    _expect(len(res["static_only"]) == 1 and res["static_only"][0]["line"] == 200, res)


def test_unrelated_events_leave_retention_runtime_only():
    static = [_sf("B/Doc.cs", 200, "Regime.PropertyChanged"),
              _sf("B/Doc.cs", 300, "CurrencyRate.Changed")]
    dump = _dump(_rec("Ns.Doc", 50, [_ev_root("Ns.Property.GBProperty", "PropertyChanged")]))
    res = C.correlate(static, dump, CFG)
    _expect(not res["confirmed"], res["confirmed"])
    _expect(len(res["runtime_only"]) == 1 and res["runtime_only"][0]["resource"] == "Ns.Doc",
            res["runtime_only"])


def test_same_member_different_holder_does_not_match():
    static = [_sf("B/Doc.cs", 100, "Foo.PropertyChanged")]
    dump = _dump(_rec("Ns.Doc", 50, [_ev_root("Ns.Bar", "PropertyChanged")]))
    res = C.correlate(static, dump, CFG)
    _expect(not res["confirmed"], res["confirmed"])


def test_namespaced_holder_normalizes_to_short_type():
    static = [_sf("B/Doc.cs", 100, "AppData.Properties.GBProperty.PropertyChanged")]
    dump = _dump(_rec("Ns.Doc", 50,
                      [_ev_root("BrokerDataClasses.Property.GBProperty", "PropertyChanged")]))
    res = C.correlate(static, dump, CFG)
    _expect(len(res["confirmed"]) == 1, res)


def test_multiple_roots_the_matching_one_is_reported():
    static = [_sf("B/Doc.cs", 100, "AppData.Properties.GBProperty.PropertyChanged")]
    dump = _dump(_rec("Ns.Doc", 50, [_ev_root("Ns.Property.PrintProperty", "PropertyChanged"),
                                     _ev_root("Ns.Property.GBProperty", "PropertyChanged")]))
    res = C.correlate(static, dump, CFG)
    _expect(len(res["confirmed"]) == 1, res)
    f = res["confirmed"][0]
    _expect("GBProperty.PropertyChanged" in f["message"] and "PrintProperty" not in f["message"], f)
    _expect(f.get("root_holder", "").endswith("GBProperty")
            and f.get("root_member") == "PropertyChanged", f)


def test_no_root_identity_keeps_type_level_fallback():
    static = [_sf("B/Doc.cs", 100, "AppData.Properties.GBProperty.PropertyChanged")]
    dump = _dump(_rec("Ns.Doc", 50, []))          # retention with no root identity at all
    res = C.correlate(static, dump, CFG)
    _expect(len(res["confirmed"]) == 1, res)


def test_unparseable_event_identity_is_conservative():
    static = [_sf("B/Doc.cs", 100, None)]         # message carries no event '...' form
    dump = _dump(_rec("Ns.Doc", 50, [_ev_root("Ns.Property.GBProperty", "PropertyChanged")]))
    res = C.correlate(static, dump, CFG)
    _expect(not res["confirmed"], res["confirmed"])
    _expect(len(res["static_only"]) == 1, res)
    _expect(len(res["runtime_only"]) == 1, res)


def test_non_event_categories_behave_exactly_as_before():
    static = [_sf("B/Doc.cs", 100, None, cat="idisposable-leak", rule="OWN-TIMER")]
    dump = _dump(_rec("Ns.Doc", 50, [_ev_root("Ns.Property.GBProperty", "PropertyChanged")]))
    res = C.correlate(static, dump, CFG)
    _expect(len(res["confirmed"]) == 1, res)      # type-level fallback untouched


def _load(name):
    with open(os.path.join(ROOT, "runtime", "fixtures", name), encoding="utf-8") as fh:
        return json.load(fh)


def test_gtd_transition_pre_278_is_runtime_only():
    res = C.correlate(_load("gtd-transition-pre.json")["findings"],
                      _load("gtd-transition-runtime.json"), CFG)
    _expect(not res["confirmed"], res["confirmed"])
    _expect(len(res["static_only"]) == 2, res["static_only"])
    ro = res["runtime_only"]
    _expect(len(ro) == 1 and ro[0]["resource"] == "BrokerDataClasses.GTD", ro)
    _expect("GBProperty.PropertyChanged" in ro[0]["message"], ro)


def test_gtd_transition_post_278_confirms_exactly_5192():
    res = C.correlate(_load("gtd-transition-post.json")["findings"],
                      _load("gtd-transition-runtime.json"), CFG)
    _expect(len(res["confirmed"]) == 1, res["confirmed"])
    f = res["confirmed"][0]
    _expect(f["line"] == 5192 and f["confidence"] == "high", f)
    _expect("GBProperty.PropertyChanged" in f["message"], f)
    _expect(len(res["static_only"]) == 2, res["static_only"])
    _expect(not res["runtime_only"], res["runtime_only"])


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            passed += 1
    print("%d/%d passed" % (passed, passed))
