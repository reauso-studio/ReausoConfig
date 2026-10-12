# Type Coercion

Environment variables are always strings. Without conversion, `DEBUG=false` would reach a `bool` field as the string `"false"` (which is truthy) and `PORT=8080` would reach an `int` field as `"8080"`.

ReausoConfig therefore converts string values to the type each field declares. This happens after [interpolation](interpolation.md), for every string value of a typed field, regardless of where it came from:

- environment variables (`${env:PORT}`)
- other interpolation results and config references (`${/server.port}`)
- quoted YAML literals (`port: "8080"`)
- [CLI overrides](composition.md#cli-overrides) (with one difference for lists, see [below](#lists))

## Example

```python
from dataclasses import dataclass
from enum import StrEnum

import rconfig as rc


class LogLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"


@dataclass
class AppConfig:
    debug: bool
    port: int
    level: LogLevel
    allowed_hosts: list[str]
    timeout: int | None


rc.register(name="app", target=AppConfig)
config = rc.instantiate(path="config.yaml", expected_type=AppConfig)
```

```yaml
# config.yaml
_target_: app
debug: '${env:APP_DEBUG ?: false}'
port: '${env:APP_PORT ?: 8000}'
level: '${env:APP_LOG_LEVEL ?: "info"}'
allowed_hosts: '${env:APP_ALLOWED_HOSTS ?: "localhost"}'
timeout: '${env:APP_TIMEOUT ?: null}'
```

With no environment variables set, the defaults are used:

```python
AppConfig(debug=False, port=8000, level=LogLevel.INFO,
          allowed_hosts=["localhost"], timeout=None)
```

With these variables set:

```bash
APP_DEBUG=yes
APP_PORT=9000
APP_LOG_LEVEL=WARNING
APP_ALLOWED_HOSTS=example.com, api.example.com
APP_TIMEOUT=30
```

the result is:

```python
AppConfig(debug=True, port=9000, level=LogLevel.WARNING,
          allowed_hosts=["example.com", "api.example.com"], timeout=30)
```

## Conversion Rules

| Declared type                          | Accepted strings                                                                                                   | Result                                 |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------ | -------------------------------------- |
| `bool`                                 | `true`, `yes`, `1`, `on` / `false`, `no`, `0`, `off` (case-insensitive, surrounding whitespace ignored)              | `True` / `False`                       |
| `int`, `float`                         | Anything `int(...)` / `float(...)` accepts                                                                          | `int` / `float`                        |
| `Enum` (incl. `StrEnum`, `IntEnum`)    | A member value (also its string form, so `"2"` matches an `IntEnum` value `2`), then a member name                  | The enum member                        |
| `pathlib.Path` and other path types    | Any string                                                                                                         | `Path(value)`                          |
| `X \| None`, `Optional[X]`             | `none`, `null`, `~` (case-insensitive), otherwise as `X`                                                           | `None` or the converted value          |
| Other unions (`int \| str`, ...)       | If `str` is a member, the string is kept; otherwise members are tried in order                                     | First member that accepts the value    |
| `list[X]`, `tuple[X, ...]`, `set[X]`   | `[a, b]` (YAML flow list) or a comma-separated list `a, b`                                                         | `list` of converted `X` items          |
| `dict[K, V]`                           | YAML flow mapping, e.g. `{a: 1, b: 2}`                                                                             | `dict`                                 |

Conversion works for nested dataclasses (including nested sections without `_target_` whose class is [inferred from the type hint](object-instantiation.md#target-resolution)), list items (`list[int]`) and dict values (`dict[str, int]`).

### Booleans

Only the tokens listed above are accepted. Anything else is an error, so a typo such as `DEBUG=ture` never silently becomes `False`.

### Lists

A value starting with `[` is parsed as a YAML flow list. Any other value is split on commas; each item is stripped and empty items are dropped:

| Environment value                 | `list[str]` result                 |
| --------------------------------- | ---------------------------------- |
| `localhost, 127.0.0.1`            | `["localhost", "127.0.0.1"]`       |
| `localhost`                       | `["localhost"]`                    |
| `[a, b]`                          | `["a", "b"]`                       |

Each item is then converted to the item type (`list[int]` turns `"1, 2"` into `[1, 2]`). Tuples and sets declared in the type hint are returned as Python lists.

!!! note "Lists on the command line"
    CLI overrides use the same rules **except** comma splitting. On the command line, write `allowed_hosts=[a, b]` for a list, because `allowed_hosts=a,b` means a [sweep](multirun-and-hooks.md#cli-syntax) over two values in multirun.

### Optional Values and Unions

For `int | None` (or `Optional[int]`), the strings `none`, `null` and `~` become `None`; any other value is converted as `int`. If a union contains `str` (for example `int | str`), the string is kept as-is.

### Enums

Enum values are matched by member value first and by member name second. With the `LogLevel` enum above, both `info` and `INFO` resolve to `LogLevel.INFO`. Invalid values raise an error listing the valid values.

## What Is Never Converted

The string is passed through unchanged when the field:

- is typed `str`, `Any` or `object`, or with a type variable,
- has no type hint, for example values inside an untyped `dict` field or inside a dict section without a registered or inferable target.

Non-string values (numbers and booleans written directly in YAML, results of arithmetic expressions) are not affected.

## Values Inside Expressions

Conversion happens once interpolation has finished, on the final value of each field. Inside an expression, an environment value is still a string. In a condition, any non-empty string counts as true, including `"false"`:

```yaml
# Wrong: USE_GPU=false still selects "cuda:0", because "false" is a non-empty string
device: '${env:USE_GPU ?: false ? "cuda:0" : "cpu"}'
```

Compare the string explicitly instead. The comparison is case-sensitive:

```yaml
# Right: selects "cuda:0" only when USE_GPU is exactly "true"
device: '${(env:USE_GPU ?: "false") == "true" ? "cuda:0" : "cpu"}'
```

The same applies to arithmetic: `${(env:WORKERS ?: 2) * 2}` yields `"33"` for `WORKERS=3`, because the string is repeated. A config reference (`${/other_field}`) also returns the other field's value before conversion. When logic depends on a typed environment value, give it its own typed field and derive the rest in Python.

## Empty Environment Variables

A variable that is set but empty (`VAR=` in a `.env` file) counts as unset: `${env:VAR}` raises `EnvironmentVariableError` ("is not set or is empty"), and `${env:VAR ?: default}` falls back to the default. An empty `APP_PORT=` therefore yields the default port instead of an error about converting `""` to `int`.

## Errors

When a value cannot be converted, `rc.instantiate()` and `rc.instantiate_multirun()` raise [`ValueCoercionError`](api-reference.md#valuecoercionerror), a subclass of `TypeMismatchError`. The message names the field, the reason, and the interpolation and environment variable the value came from:

```yaml
debug: '${env:DEBUG ?: false}'
```

```text
$ DEBUG=ture python app.py
rconfig.errors.ValueCoercionError: Invalid value for field 'debug' at 'debug': Cannot convert 'ture' to bool; expected one of 1/on/true/yes or 0/false/no/off
Value came from '${env:DEBUG ?: false}' (environment variable DEBUG)
Hint: Provide a value that can be read as 'bool'.
```

The error also exposes the details as attributes (`field`, `expected`, `value`, `reason`, `config_path`, `source_expression`, `env_vars`).

Other functions handle unconvertible values differently:

| Function                                                        | Behaviour                                                        |
| --------------------------------------------------------------- | ---------------------------------------------------------------- |
| `rc.instantiate()`, `rc.instantiate_multirun()`                 | Raise `ValueCoercionError`                                       |
| `rc.validate()`                                                 | Resolves interpolations and reports the error in `result.errors` |
| `rc.get_provenance()`                                           | Never fails; the value is left as-is                             |
| `rc.to_dict()`, `rc.to_yaml()`, `rc.to_json()`, ... `rc.export()` | Never fail; the value is exported as-is                          |

Converted values are visible everywhere: `rc.to_dict()` and the other exports emit `9000`, not `"9000"`, and a provenance entry's `.value` holds the converted value while `.interpolation.kind` still records `"env"`.

!!! note "Behaviour change: quoted YAML literals"
    Because conversion applies to every string value, a quoted literal such as `port: "8080"` for an `int` field is now accepted and converted to `8080`. Earlier versions rejected it with a type mismatch.
