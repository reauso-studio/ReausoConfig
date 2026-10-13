# Changelog

All notable changes to ReausoConfig are documented here.

## Unreleased

### Fixed

- **`+` no longer stringifies a list or a dict.** A string on either side of
  `+` builds a string, which is the point of the operator -- `"epoch " + 10` is
  `"epoch 10"`. But that applied to containers too, so `"a" + ["b"]` silently
  became the string `"a['b']"`, and no error said so. Mixing a string with a
  list or a dict now raises `InterpolationResolutionError` naming both types.

  The shape this hid is worth spelling out, because it only misbehaves once a
  variable is set: `'${(env:HOSTS ?: []) + ["localhost"]}'` yields
  `["localhost"]` with `HOSTS` unset, and a list of mangled strings once it is.
  Lists concatenate as before, and so does every other use of `+`.

### Added

- **`int()` and `float()` in expressions.** An `${env:...}` reference is a
  string wherever it is only part of a larger expression -- it is converted to
  the declared field type only when it is the whole value of a key -- so
  `'${(env:WORKERS ?: 2) * 2}'` repeats the string rather than multiplying.
  `'${int(env:WORKERS ?: 2) * 2}'` does the arithmetic. A value that cannot be
  converted raises `InterpolationResolutionError` quoting it.

## 0.2.0

This release makes ReausoConfig behave well as a library embedded in another
program (web app, worker, test runner), and lets typed fields read their values
from environment variables.

### Breaking changes

- **CLI overrides and `--help` are now opt-in.** `cli_overrides` defaults to
  `None` on every public function, which follows the new process-wide setting.
  That setting is off by default, so loading a config no longer reads or modifies
  `sys.argv`. Scripts that relied on the old default call this once at startup:

  ```python
  rc.set_cli_overrides(True)
  ```

  Alternatively, pass `cli_overrides=True` per call.
- **String values are converted to the declared field type.** After
  interpolation, a string in a field typed `bool`, `int`, `float`, an `Enum`, a
  path, a list, or an optional/union of these is converted to that type. This
  includes quoted YAML literals, so `port: "8080"` is now accepted for an `int`
  field instead of being rejected. Fields typed `str` or `Any`, and untyped
  values, are never converted.
- **An empty environment variable counts as unset.** `VAR=` makes
  `${env:VAR ?: default}` fall back to the default. `${env:VAR}` without a
  default raises `EnvironmentVariableError`.
- **`validate()` resolves interpolations** before checking types, the same
  way `instantiate()` does. An interpolation error is now raised by `validate()`
  unless it depends on an unsatisfied `_required_` value, which is reported as a
  `RequiredValueError` as before.

### Added

- Environment values reach typed fields: `${env:DEBUG ?: false}` yields a real
  `bool` for a `bool` field, and the same holds for `int`, `float`, enums, paths,
  `X | None`, and lists. A comma-separated value such as
  `ALLOWED_HOSTS=localhost, 127.0.0.1` becomes `["localhost", "127.0.0.1"]` for a
  `list[str]` field.
- Conversion applies in `instantiate()`, `instantiate_multirun()`, `validate()`,
  `get_provenance()` (entry values hold the converted value), and all exporters.
- `rc.set_cli_overrides()` and `rc.cli_overrides_enabled()` control the
  process-wide CLI policy.
- `rc.ValueCoercionError` (a `TypeMismatchError`) reports values that cannot be
  converted, naming the field, the value, the original `${...}` expression, and
  any environment variables it used.
- Unrecognised boolean tokens such as `ture` raise instead of reading as false.
  The accepted tokens are `true/yes/1/on` and `false/no/0/off`.
- Invalid enum values list the valid values in the error.
- The package ships `py.typed`, so type checkers use its annotations.
- New documentation pages: "Type Coercion" and "Embedding in Applications".

### Fixed

- PEP 604 unions (`int | None`) are validated and coerced correctly. Previously
  only `typing.Optional` / `typing.Union` worked.
- Fields typed `Any` no longer crash validation.
- CLI overrides on `Optional`/union fields are coerced instead of failing.
- `--help` no longer applies other command-line arguments as overrides when
  building the help output, so `--help` combined with an unrelated `key=value`
  argument shows help instead of raising `InvalidOverridePathError`.
- Documentation: corrected environment-variable syntax (`${env:VAR ?: default}`;
  there is no comma form), removed examples using syntax that does not exist
  (`${= ...}`, `${if:...}`), fixed the documentation and repository URLs
  (`reauso-studio`), and added PyPI installation instructions
  (`pip install reausoconfig`, imported as `rconfig`).

## 0.1.0

- Initial release.
