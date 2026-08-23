---
name: cwe-502-insecure-deserialization
description: Curated fix guidance for CWE-502 (deserialization of untrusted data) findings -- how to patch a Newtonsoft.Json / System.Text.Json / Java ObjectInputStream deserialization call so it can no longer be steered into instantiating attacker-chosen types.
when_to_use: patching a Semgrep finding whose cwe_ids include CWE-502, before writing the patch
keywords: [deserialization, insecure-deserialization, jsonconvert, typenamehandling, objectinputstream, cwe-502]
---
The vulnerability is not "deserialization" in general -- it is a deserializer
that lets the *input itself* decide which type gets instantiated. Untrusted
data must never control which class is constructed.

**Newtonsoft.Json (JsonConvert / JsonSerializer).** The unsafe setting is
`TypeNameHandling` set to anything other than `None` (`Auto`, `Objects`,
`All`, `Arrays`) on a serializer/settings object that touches untrusted
input. Fix by passing an explicit `JsonSerializerSettings` with
`TypeNameHandling = TypeNameHandling.None` to the deserializing call. If the
code genuinely needs polymorphic type discrimination (rare, and worth
questioning), the only acceptable alternative is `TypeNameHandling.Auto`
paired with a custom `SerializationBinder` that allowlists the exact concrete
types permitted -- never leave type resolution unconstrained.

**System.Text.Json.** Prefer a fixed, statically-known target type for
`JsonSerializer.Deserialize<T>` (no `object`/`dynamic` target for untrusted
input). If polymorphism is required, use an explicit, allowlisted
`JsonConverter`/discriminator scheme you control -- never trust a
`$type`-style field from the payload to select the concrete type.

**Java (`ObjectInputStream` / native serialization).** Prefer avoiding native
(de)serialization of untrusted data entirely: deserialize via a JSON library
(Jackson/Gson) into a fixed, known target class instead of using
`ObjectInputStream.readObject()`. If `ObjectInputStream` is unavoidable
(e.g. an existing wire format you can't change), install an
`ObjectInputFilter` that allowlists the exact classes permitted and rejects
everything else, applied before `readObject()` is ever called.

**General rule for whichever language you're in:** the fix is an allowlist
(of settings, types, or classes), not a blocklist, and not "try/catch the
exception and hope." A fix that leaves the deserializer able to resolve an
arbitrary type -- just with a warning suppressed, or a try/catch around it --
has not fixed CWE-502.

**Read before you edit.** Only edit a file this run has actually read; do not
reconstruct surrounding code from memory.

**Change the code, not the test.** If a test or config file appears to
require the unsafe setting, say so and leave it -- don't relax a test to make
an unsafe pattern pass.

**Smallest safe change.** Patch the specific flagged call/settings object.
Do not refactor unrelated deserialization call sites in the same file as
part of this fix.
