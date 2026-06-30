# Project Documentation Rules (Non-Obvious Only)

- `README.md` states the key boundary: this repo is the lift-out home, while `Own.NET/audit/` is still canonical.
- `src/` is a thin reserved .NET skeleton, not the main implemented auditor; most active/testable logic is Python under `arch/`, `fix/`, `leakmine/`, `report/`, and `runtime/`.
- `oracle/LeakyOracle` is an Avalonia leak oracle fixture used to prove arch/runtime passes, not the production target.
- `sts_audit/` holds local audit artifacts/contracts consumed by CLIs; many CLIs default there and fail cleanly when stand-produced files are absent.
- `fix/README.md` is the best concise map for the fix arm; `docs/fix-arm.md` has the full safety design.
