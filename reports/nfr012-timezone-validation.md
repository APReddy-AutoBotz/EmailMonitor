# NFR-012 explicit timezone display acceptance

Scope: NFR-012, EM-012 and the UTC-derived local display requirement in
`docs/03-user-experience.md`. Existing presentation code already supplies the
configured timezone, labels it, preserves the machine-readable source instant,
and labels unsupported-zone fallback. This increment adds acceptance evidence;
it changes no runtime behavior.

Eight render cases cover UTC default, a fractional offset crossing midnight,
spring DST's missing hour, autumn DST's repeated hour with distinct source
instants, a changed display zone, unsupported-zone UTC fallback and two invalid
instant inputs. Tests use a deterministic browser locale with the actual Intl
conversion rules, not mocked conversion outputs. Repeated local times retain
separate `dateTime` values; the visible timezone label alone is not claimed to
disambiguate the repeated hour.

Normal frontend gate: 156 tests passed across 19 files; type checking, lint and
production build passed. Independent fresh validation is recorded separately.
This is render-level coverage, not installed-browser certification, durable UTC
persistence proof, Unicode/export round-trip proof or complete NFR-012 closure.
No schema, authority, policy, live-source, dependency or production-code changes.
