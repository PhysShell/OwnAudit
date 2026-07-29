#!/usr/bin/env python3
"""
`producer-provenance/v1` - the input sidecar that tells the normalizer WHICH RUN
produced each SARIF file (issue Own.NET#266, slice 1B).

SARIF does not carry a run identity. It carries a tool name, sometimes a
version, and results - nothing that says "this is the audit of 2026-07-29T10:00Z
against commit abc123 with this configuration". Without that, an occurrence
cannot be identified, because "the same finding" and "the same finding in the
same run" are different claims.

So the run identity comes from OUTSIDE the SARIF, from a manifest the runner
writes as it goes:

    {
      "schema_version": "producer-provenance/v1",
      "inputs": {
        "own-check": {
          "producer_run_id": "audit-20260729T100000Z/own-check",
          "producer_name":   "own-check",
          "producer_version": null,
          "input_digest":    "sha256:...",
          "config_digest":   null,
          "source_commit":   "..."
        }
      }
    }

THE FOUR RULES THIS MODULE EXISTS TO ENFORCE
--------------------------------------------
1. **Read metadata, never invent it.** This module does not generate a
   `producer_run_id`, not even a plausible one. A run id minted at normalization
   time would describe the normalization, not the analysis, and would change
   every time the same recorded run was re-normalized - which is the opposite of
   what an identity is for. No manifest entry means no run id means no
   occurrence id, and the record says so out loud.
2. **Verify the digest of the exact file read.** The manifest claims a
   `producer_run_id` for particular bytes. If the SARIF on disk is not those
   bytes, the claim is about something else.
3. **A mismatch is rejected, not degraded.** Silently falling back to "unknown
   run" on a mismatch would turn a wrong manifest into a slightly emptier
   report, which nobody would investigate.
4. **Missing fields stay explicitly null.** `producer_version`, `config_digest`
   and `source_commit` are frequently unknown - in the recorded STS corpus only
   CodeQL reports a version at all. They are carried as `null` rather than
   omitted, so a consumer reads "we do not know" instead of inferring "there is
   no such thing".

`input_digest` IS NOT A RUN ID
------------------------------
It is tempting, and wrong. Two separate runs over an unchanged tree can
serialize to identical bytes; two serializers of one run can produce different
bytes. The digest binds a manifest entry to a file - that is all it does, and
that is why it is a provenance field rather than an identity.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONTRACT = "producer-provenance/v1"

#: Fields carried through to the payload, in this order. Anything the manifest
#: does not supply is `None` - present and null, never absent.
FIELDS = ("producer_run_id", "producer_name", "producer_version",
          "input_digest", "config_digest", "source_commit")


class ProvenanceError(RuntimeError):
    """The manifest is unusable: wrong contract, or it describes other bytes."""


@dataclass
class ProducerProvenance:
    """One producer's run metadata, as resolved against the file actually read."""

    producer_name: str
    producer_run_id: str | None = None
    producer_version: str | None = None
    input_digest: str | None = None
    config_digest: str | None = None
    source_commit: str | None = None
    #: True only when a manifest digest was present AND matched the bytes read.
    #: Recorded rather than assumed: an entry with no `input_digest` is not
    #: proof of anything, and a reader must be able to tell the two apart.
    digest_verified: bool = False
    #: `"manifest"` | `"sarif-driver"` | None. Where `producer_version` came from.
    #: A version is worth little without knowing whether the runner asserted it or
    #: the tool self-reported it in its own output.
    producer_version_source: str | None = None
    #: Why this producer has no run id, when it has none.
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {k: getattr(self, k) for k in FIELDS}
        out["producer_version_source"] = self.producer_version_source
        out["digest_verified"] = self.digest_verified
        if self.note:
            out["note"] = self.note
        return out


def check_unique_producers(sarif_inputs: list[tuple[str, str]]) -> None:
    """One `--sarif` input per producer name, enforced rather than assumed.

    Provenance is keyed by producer name and a record joins to it through its
    `tool`, so two inputs under one name cannot be told apart: both runs would
    answer to the same key, and every finding would point at whichever entry
    happened to survive. Input-instance identity is a bigger model than this slice
    carries, so until it exists this is the real contract - and a real contract
    fails loudly instead of resolving arbitrarily.
    """
    seen: dict[str, str] = {}
    for tool, sarif_path in sarif_inputs:
        if tool in seen:
            raise ProvenanceError(
                f"duplicate --sarif producer key {tool!r}: {seen[tool]!r} and {sarif_path!r}. "
                "One input per producer: provenance is keyed by producer name, so two runs "
                "under one name cannot be represented. Give the second one its own producer "
                "name.")
        seen[tool] = sarif_path


def sha256_file(path: str | Path) -> str:
    with open(path, "rb") as fh:
        return "sha256:" + hashlib.sha256(fh.read()).hexdigest()


def load_manifest(path: str | Path) -> dict[str, dict[str, Any]]:
    """Read the manifest and return its `inputs` map, keyed by producer name.

    A wrong `schema_version` is an error rather than a best-effort read: the
    whole point of the file is to be the authority on run identity, and a file
    of unknown shape cannot be that.
    """
    # utf-8-sig, not utf-8: this file is written by another program - `Run-Audit.ps1`
    # via `Set-Content -Encoding utf8`, which emits a BOM under Windows PowerShell 5.1
    # and none under pwsh 7. A BOM would make `json.loads` fail with "Expecting value",
    # which reads as a corrupt manifest rather than as an encoding detail. `utf-8-sig`
    # strips one if present and is identical to `utf-8` otherwise.
    doc = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(doc, dict):
        # `[]`, `null`, a bare string or number are all valid JSON. Reaching for
        # `.get` on them raises AttributeError, which escapes the ProvenanceError
        # handler in the CLI and exits 1 with a traceback - so a malformed manifest
        # would report itself differently depending on HOW it was malformed. Every
        # bad manifest exits 2 with a sentence.
        raise ProvenanceError(
            f"provenance manifest {path}: the document root must be an object, got "
            f"{type(doc).__name__}")
    got = doc.get("schema_version")
    if got != CONTRACT:
        raise ProvenanceError(
            f"provenance manifest {path}: schema_version is {got!r}, expected {CONTRACT!r}")
    inputs = doc.get("inputs")
    if not isinstance(inputs, dict):
        raise ProvenanceError(f"provenance manifest {path}: 'inputs' must be an object")

    # Types are checked here rather than trusted. A manifest is written by another
    # program, and a `producer_run_id` that arrived as a number or a list would
    # otherwise surface as an AttributeError somewhere far from the cause - or, worse,
    # be str()-ed into a plausible-looking run identity that nothing ever produced.
    for tool, entry in inputs.items():
        if not isinstance(tool, str) or not tool:
            raise ProvenanceError(f"provenance manifest {path}: producer key {tool!r} "
                                  "must be a non-empty string")
        if not isinstance(entry, dict):
            raise ProvenanceError(f"provenance manifest {path}: inputs[{tool!r}] must be an "
                                  f"object, got {type(entry).__name__}")
        for f in FIELDS:
            v = entry.get(f)
            if v is not None and not isinstance(v, str):
                raise ProvenanceError(
                    f"provenance manifest {path}: inputs[{tool!r}].{f} must be a string or "
                    f"null, got {type(v).__name__} ({v!r})")
    return inputs


def resolve(sarif_inputs: list[tuple[str, str]],
            manifest_path: str | Path | None,
            observed_versions: dict[str, str | None] | None = None,
            ) -> dict[str, ProducerProvenance]:
    """Resolve provenance for each `(tool, sarif_path)` the normalizer will read.

    With no manifest every producer resolves to "run unknown" - which is the
    honest state for the recorded STS corpus, whose SARIF predates this contract.
    That is a legacy boundary, not a schema defect: those runs really cannot be
    identified after the fact, and a report that claimed otherwise would be
    making it up.

    `observed_versions` carries what the SARIF driver actually declared (CodeQL is
    the only producer in the corpus that declares one). It fills `producer_version`
    only when the manifest did not, and `producer_version_source` records which of
    the two it came from - a known value must not be reported as unknown, and a
    value must not be reported without saying where it came from.
    """
    observed = observed_versions or {}
    out: dict[str, ProducerProvenance] = {}

    check_unique_producers(sarif_inputs)
    entries = load_manifest(manifest_path) if manifest_path else {}

    for tool, sarif_path in sarif_inputs:
        entry = entries.get(tool)
        if entry is None:
            out[tool] = ProducerProvenance(
                producer_name=tool,
                producer_version=observed.get(tool),
                producer_version_source="sarif-driver" if observed.get(tool) else None,
                note=("no manifest entry for this producer"
                      if manifest_path else "no provenance manifest supplied"))
            continue

        digest_claimed = entry.get("input_digest")
        verified = False
        if digest_claimed:
            digest_actual = sha256_file(sarif_path)
            if digest_claimed != digest_actual:
                raise ProvenanceError(
                    f"provenance manifest describes different bytes for {tool!r}:\n"
                    f"  manifest input_digest = {digest_claimed}\n"
                    f"  sha256({sarif_path})  = {digest_actual}\n"
                    "  the run id in the manifest is a claim about a file this is not; "
                    "re-run the producer or regenerate the manifest.")
            verified = True

        name = entry.get("producer_name") or tool
        if name != tool:
            raise ProvenanceError(
                f"provenance manifest: entry {tool!r} declares producer_name {name!r}; "
                "the key and the declared name must agree, or the record's `tool` and its "
                "provenance would describe different producers.")

        run_id = entry.get("producer_run_id") or None
        declared = entry.get("producer_version")
        version = declared or observed.get(tool)
        out[tool] = ProducerProvenance(
            producer_name=name,
            producer_run_id=run_id,
            producer_version=version,
            producer_version_source=("manifest" if declared
                                     else "sarif-driver" if version else None),
            input_digest=digest_claimed,
            config_digest=entry.get("config_digest"),
            source_commit=entry.get("source_commit"),
            digest_verified=verified,
            note=None if run_id else "manifest entry carries no producer_run_id")

    return out


def unused_entries(sarif_inputs: list[tuple[str, str]],
                   manifest_path: str | Path | None) -> list[str]:
    """Manifest entries no `--sarif` input claimed.

    Surfaced in the coverage ledger rather than raised: a manifest may legitimately
    describe a producer whose SARIF was not folded into this particular run. But it
    may equally be a typo in a tool name, which would silently cost that producer
    its whole run identity - so it is reported, not ignored.
    """
    if not manifest_path:
        return []
    entries = load_manifest(manifest_path)
    claimed = {tool for tool, _ in sarif_inputs}
    return sorted(k for k in entries if k not in claimed)
