# API Reference

## Type Aliases

- **`StrOrPath`**: `str | os.PathLike[str]` - All path parameters accept strings directly, Path objects, or any os.PathLike implementation. Import with `from rconfig import StrOrPath` for type annotations in your own code.

## Common API

Core functions for everyday use. These are the primary interfaces most users will interact with.

### `rc.register(name, target)`

Register a target class under a unique name for use in config files.

**Parameters:**

| Parameter  | Type     | Default  | Description                                                                            |
| ---------- | -------- | -------- | -------------------------------------------------------------------------------------- |
| `name`   | `str`  | required | Unique identifier for the target class. This is the value used in `_target_` fields. |
| `target` | `type` | required | The Python class to register.                                                          |

**Returns:** `None`

**Raises:**

| Exception      | Condition                         |
| -------------- | --------------------------------- |
| `ValueError` | If `name` is already registered |

**Examples:**

```python
rc.register(name="model", target=ModelConfig)
rc.register(name="my_dataset", target=MyDataset)
```

### `rc.unregister(name)`

Remove a previously registered configuration reference.

**Parameters:**

| Parameter | Type    | Default  | Description                                |
| --------- | ------- | -------- | ------------------------------------------ |
| `name`  | `str` | required | Identifier of the reference to unregister. |

**Returns:** `None`

**Raises:**

| Exception    | Condition                             |
| ------------ | ------------------------------------- |
| `KeyError` | If no reference with that name exists |

**Examples:**

```python
rc.unregister(name="model")
```

### `rc.validate(path, *, inner_path=None, overrides=None, cli_overrides=None)`

Validate a config file without instantiating (dry-run). Checks all `_required_` values have been satisfied. Like `rc.instantiate()`, it resolves `${...}` interpolations first and [converts string values](type-coercion.md) to the declared field types, so a value that cannot be converted is reported as a `ValueCoercionError` in `errors`.

**Parameters:**

| Parameter         | Type                      | Default  | Description                                                                     |
| ----------------- | ------------------------- | -------- | ------------------------------------------------------------------------------- |
| `path`          | `StrOrPath`             | required | Path to the configuration file. Accepts str, Path, or any os.PathLike.          |
| `inner_path`    | `str \| None`            | `None` | Dot-notation path to validate only a section (e.g., `"model"` or `"trainer.callbacks[0]"`). `_required_` markers outside this section are ignored. When specified, the root-level `_target_` is optional and types can be inferred from parent's type hints (including `list[X]`, `set[X]`, `dict[str, X]`, `Sequence[X]`, `Mapping[K, V]`, `tuple[A, B, C]`, `Optional[container]`, `Annotated[X, ...]`, `NewType`, and `Union[A, B]` via structural matching). |
| `overrides`     | `dict[str, Any] \| None` | `None` | Dictionary of config overrides using dot notation keys.                         |
| `cli_overrides` | `bool \| None` | `None` | Parse CLI overrides and `--help` from `sys.argv`. `None` uses `rc.set_cli_overrides()` (off by default). |

**Returns:** `ValidationResult` with fields:

- `valid` (`bool`): `True` if validation passed with no errors
- `errors` (`list[ValidationError]`): List of validation errors found

**Raises:**

| Exception               | Condition                                          |
| ----------------------- | -------------------------------------------------- |
| `ConfigFileError`     | If file cannot be loaded or parsed                 |
| `InvalidInnerPathError` | If `inner_path` doesn't exist or points to a scalar |

**Examples:**

```python
result = rc.validate(path=Path("config.yaml"))
if result.valid:
    print("Config is valid!")
else:
    for error in result.errors:
        print(error)

# With overrides to satisfy _required_ values
result = rc.validate(
    path=Path("config.yaml"),
    overrides={"api_key": "secret123"},
)

# Validate only a section
result = rc.validate(path=Path("trainer.yaml"), inner_path="model")
```

### `rc.instantiate(path, expected_type=None, *, inner_path=None, overrides=None, cli_overrides=None, lazy=False)`

Load, compose, validate, and instantiate a configuration file into Python objects.

**Parameters:**

| Parameter         | Type                      | Default   | Description                                                                                                                                     |
| ----------------- | ------------------------- | --------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `path`          | `StrOrPath`             | required  | Path to the configuration file. Accepts str, Path, or any os.PathLike. Supports `.yaml`, `.yml`, `.json`, `.toml`.                      |
| `expected_type` | `type[T] \| None`        | `None`  | Optional type for type-safe returns. Enables IDE autocompletion and type checking.                                                              |
| `inner_path`    | `str \| None`            | `None`  | Dot-notation path to instantiate only a section (e.g.,`"model.encoder"` or `"trainer.callbacks[0]"`). Interpolations are resolved from the full config before extraction. When specified, the root-level `_target_` is optional and types can be inferred from parent's type hints (including `list[X]`, `set[X]`, `dict[str, X]`, `Sequence[X]`, `Mapping[K, V]`, `tuple[A, B, C]`, `Optional[container]`, `Annotated[X, ...]`, `NewType`, and `Union[A, B]` via structural matching). |
| `overrides`     | `dict[str, Any] \| None` | `None`  | Config overrides using dot notation keys. Applied before CLI overrides.                                                                         |
| `cli_overrides` | `bool \| None` | `None` | Parse CLI overrides and `--help` from `sys.argv`. `None` uses `rc.set_cli_overrides()` (off by default). |
| `lazy`          | `bool`                  | `False` | If `True`, all nested configs delay `__init__` until first attribute access.                                                                |

**Returns:** `T` if `expected_type` provided, otherwise `Any`

**Raises:**

| Exception                      | Condition                                   |
| ------------------------------ | ------------------------------------------- |
| `ConfigFileError`            | File cannot be loaded or parsed             |
| `TargetNotFoundError`        | `_target_` value not registered           |
| `ValidationError`            | Config structure is invalid                 |
| `ValueCoercionError`         | A string value cannot be converted to the field's declared type |
| `RequiredValueError`         | `_required_` value not provided           |
| `CircularRefError`           | Circular `_ref_` references detected      |
| `CircularInstanceError`      | Circular `_instance_` references detected |
| `RefResolutionError`         | A `_ref_` cannot be resolved              |
| `InstanceResolutionError`    | An `_instance_` path cannot be resolved   |
| `InvalidInnerPathError`      | `inner_path` doesn't exist in config      |
| `InvalidOverridePathError`   | An override path doesn't exist              |
| `InvalidOverrideSyntaxError` | An override string is malformed             |
| `InstantiationError`         | Object creation fails                       |

**Examples:**

```python
# Basic usage - string paths work directly
model = rc.instantiate(path="config.yaml")

# Type-safe with IDE autocompletion
model = rc.instantiate(path="config.yaml", expected_type=ModelConfig)

# Partial instantiation
encoder = rc.instantiate(path="trainer.yaml", inner_path="model.encoder")

# With programmatic overrides
model = rc.instantiate(
    path="config.yaml",
    overrides={"learning_rate": 0.001},
)

# Read key=value overrides and --help from sys.argv for this call only
model = rc.instantiate(path="config.yaml", cli_overrides=True)

# Lazy instantiation
app = rc.instantiate(path="app.yaml", lazy=True)

# Path objects also work
from pathlib import Path
model = rc.instantiate(path=Path("config.yaml"))
```

### `rc.instantiate_multirun(path, expected_type=None, *, sweep=None, experiments=None, overrides=None, inner_path=None, cli_overrides=None, lazy=False)`

Generate and instantiate multiple config combinations from sweep parameters and experiments. See [Multirun Support](multirun-and-hooks.md#multirun-support) for detailed usage examples.

**Parameters:**

| Parameter         | Type                              | Default   | Description                                                                                                                                     |
| ----------------- | --------------------------------- | --------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `path`          | `StrOrPath`                     | required  | Path to the base configuration file. Accepts str, Path, or any os.PathLike.                                                                     |
| `expected_type` | `type[T] \| None`                | `None`  | Optional type for type-safe returns.                                                                                                            |
| `sweep`         | `dict[str, list[Any]] \| None`  | `None`  | Dict of parameter paths to lists of values. All combinations (cartesian product) are generated.                                                |
| `experiments`   | `list[dict[str, Any]] \| None`  | `None`  | List of explicit experiment override dicts.                                                                                                     |
| `overrides`     | `dict[str, Any] \| None`         | `None`  | Constant overrides applied to all runs (lowest priority).                                                                                       |
| `inner_path`    | `str \| None`                    | `None`  | Dot-notation path to instantiate only a section (e.g., `"model"`). Interpolations are resolved from the full config before extraction.       |
| `cli_overrides` | `bool \| None` | `None` | Parse CLI overrides and `--help` from `sys.argv`. `None` uses `rc.set_cli_overrides()` (off by default). |
| `lazy`          | `bool`                          | `False` | If `True`, nested configs delay `__init__` until first attribute access.                                                                    |

**Returns:** `MultirunIterator[T]` if `expected_type` provided, otherwise `MultirunIterator[Any]`

**Raises:**

| Exception                 | Condition                                            |
| ------------------------- | ---------------------------------------------------- |
| `NoRunConfigurationError` | Neither `sweep` nor `experiments` provided         |
| `InvalidSweepValueError`  | Sweep values are not lists                           |
| `InvalidInnerPathError`   | `inner_path` doesn't exist in config (when accessed) |

**Examples:**

```python
# Sweep with partial instantiation - string paths work directly
for result in rc.instantiate_multirun(
    path="trainer.yaml",
    inner_path="model",
    sweep={"lr": [0.01, 0.001]},
):
    model = result.instance  # Only the model section

# Combined sweep and experiments
for result in rc.instantiate_multirun(
    path="config.yaml",
    experiments=[{"model": "resnet"}, {"model": "vit"}],
    sweep={"lr": [0.01, 0.001]},
):
    train(result.instance)  # 4 runs total
```

### `rc.known_targets()`

Get a read-only view of all registered configuration references.

**Parameters:** None

**Returns:** `MappingProxyType[str, TargetEntry]` - Immutable mapping of name to `TargetEntry`

`TargetEntry` has attributes:

- `name` (`str`): Identifier for the target class
- `target_class` (`type[Any]`): The registered class
- `decisive_init_parameters` (`MappingProxyType[str, Parameter]`): Constructor parameters

**Examples:**

```python
refs = rc.known_targets()
for name, ref in refs.items():
    print(f"{name}: {ref.target_class}")
    for param_name, param in ref.decisive_init_parameters.items():
        print(f"  {param_name}: {param.annotation}")
```

### `rc.get_provenance(path, *, inner_path=None, overrides=None, cli_overrides=None)`

Compose a config file and track the origin of each value.

**Parameters:**

| Parameter       | Type                      | Default  | Description                                                                         |
| --------------- | ------------------------- | -------- | ----------------------------------------------------------------------------------- |
| `path`          | `StrOrPath`             | required | Path to the entry-point config file. Accepts str, Path, or any os.PathLike.         |
| `inner_path`    | `str \| None`            | `None` | If specified, returns provenance only for this section. Uses lazy loading.          |
| `overrides`     | `dict[str, Any] \| None` | `None` | Dictionary of config overrides using dot notation keys.                             |
| `cli_overrides` | `bool \| None` | `None` | Parse CLI overrides and `--help` from `sys.argv`. `None` uses `rc.set_cli_overrides()` (off by default). |

**Returns:** `Provenance` object with methods:

- `get(path: str) -> ProvenanceEntry | None`: Get entry for a specific config path
- `items() -> Iterator[tuple[str, ProvenanceEntry]]`: Iterate all (path, entry) tuples
- `trace(path: str) -> ProvenanceNode | None`: Get full tree for a path
- `to_dict() -> dict`: Export as dictionary

Use `rc.format(prov)` for customized output formatting.

Entry values are [type-converted](type-coercion.md) like in `rc.instantiate()` (an env value `"8080"` for an `int` field is reported as `8080`; `entry.interpolation.kind` is still `"env"`). A value that cannot be converted is left unchanged instead of raising.

**Examples:**

```python
# String paths work directly
prov = rc.get_provenance(path="trainer.yaml")
print(prov)  # Default formatting

entry = prov.get("model.layers")
print(f"Defined at: {entry.file}:{entry.line}")

# Custom formatting
print(rc.format(prov).minimal())
print(rc.format(prov).for_path("/model.*"))

# Partial provenance - only loads files needed for model section
prov = rc.get_provenance(path="trainer.yaml", inner_path="model")

# With overrides
prov = rc.get_provenance(
    path=Path("config.yaml"),
    overrides={"model.lr": 0.01}
)

# Include CLI overrides from sys.argv in the provenance
prov = rc.get_provenance(path=Path("config.yaml"), cli_overrides=True)
```

### `rc.diff(left, right, *, left_inner_path=None, right_inner_path=None, left_overrides=None, right_overrides=None, cli_overrides=False)`

Compare two configurations and report differences.

**Parameters:**

| Parameter           | Type                        | Default   | Description                                                              |
| ------------------- | --------------------------- | --------- | ------------------------------------------------------------------------ |
| `left`            | `StrOrPath \| Provenance`   | required  | Left (base) config. Path or existing Provenance object.                  |
| `right`           | `StrOrPath \| Provenance`   | required  | Right (new) config. Path or existing Provenance object.                  |
| `left_inner_path` | `str \| None`               | `None`  | Dot-notation path to compare only a section of the left config.          |
| `right_inner_path`| `str \| None`               | `None`  | Dot-notation path to compare only a section of the right config.         |
| `left_overrides`  | `dict[str, Any] \| None`    | `None`  | Overrides for left config (ignored if left is Provenance).               |
| `right_overrides` | `dict[str, Any] \| None`    | `None`  | Overrides for right config (ignored if right is Provenance).             |
| `cli_overrides`   | `bool`                      | `False` | Whether to parse CLI overrides from `sys.argv`.                        |

**Returns:** `ConfigDiff` - Immutable object with `added`, `removed`, `changed`, `unchanged` views. Each view is a `MappingProxyType[str, DiffEntry]`.

Use `rc.format(diff)` for customized output formatting.

**Examples:**

```python
# Compare two config files
diff = rc.diff(Path("config_v1.yaml"), Path("config_v2.yaml"))

# Compare same file with different overrides
diff = rc.diff(
    Path("config.yaml"),
    Path("config.yaml"),
    left_overrides={"model.lr": 0.001},
    right_overrides={"model.lr": 0.01},
)

# Reuse existing provenance for efficiency
prov_v1 = rc.get_provenance(path="v1.yaml")
prov_v2 = rc.get_provenance(path="v2.yaml")
diff = rc.diff(prov_v1, prov_v2)

# Compare specific sections
diff = rc.diff(
    Path("v1.yaml"), Path("v2.yaml"),
    left_inner_path="model",
    right_inner_path="model",
)
```

### `rc.format(obj, layout=None)`

Format a Provenance or ConfigDiff object for display. Returns a fluent builder for configuring output via method chaining.

**Parameters:**

| Parameter | Type                              | Default  | Description                                                          |
| --------- | --------------------------------- | -------- | -------------------------------------------------------------------- |
| `obj`   | `Provenance \| ConfigDiff`        | required | The object to format.                                                |
| `layout`| `ProvenanceLayout \| None`        | `None` | Optional custom layout (Provenance only). Ignored for ConfigDiff.    |

**Returns:** `ProvenanceFormat` when given Provenance, `DiffFormat` when given ConfigDiff. Both support method chaining for presets, show/hide toggles, filtering, and layout selection.

**Raises:**

| Exception     | Condition                                  |
| ------------- | ------------------------------------------ |
| `TypeError` | If `obj` is not a Provenance or ConfigDiff |

**Examples:**

```python
# Provenance formatting
prov = rc.get_provenance(path="config.yaml")
print(rc.format(prov).minimal())
print(rc.format(prov).for_path("/model.*").tree())
print(rc.format(prov).full().flat())

# Diff formatting
diff = rc.diff(Path("v1.yaml"), Path("v2.yaml"))
print(rc.format(diff).terminal())
print(rc.format(diff).show_provenance().markdown())
print(rc.format(diff).changes_only().tree())
```

### `rc.set_cache_size(size)`

Configure the LRU cache for loaded config files.

**Parameters:**

| Parameter | Type    | Default  | Description                                             |
| --------- | ------- | -------- | ------------------------------------------------------- |
| `size`  | `int` | required | Cache size. Use `0` for unlimited (default behavior). |

**Returns:** `None`

**Examples:**

```python
rc.set_cache_size(size=100)  # Cache up to 100 files
rc.set_cache_size(size=0)    # Unlimited (default)
```

### `rc.clear_cache()`

Clear the config file cache.

**Parameters:** None

**Returns:** `None`

**Examples:**

```python
rc.clear_cache()
```

### `rc.is_lazy_proxy(obj)`

Check if an object is an uninitialized lazy proxy.

**Parameters:**

| Parameter | Type    | Default  | Description      |
| --------- | ------- | -------- | ---------------- |
| `obj`   | `Any` | required | Object to check. |

**Returns:** `bool` - `True` if object is a lazy proxy that hasn't been initialized yet

**Examples:**

```python
model = rc.instantiate(path=Path("config.yaml"), lazy=True)
print(rc.is_lazy_proxy(obj=model))  # True
_ = model.hidden_size  # Triggers initialization
print(rc.is_lazy_proxy(obj=model))  # False
```

### `rc.force_initialize(obj)`

Force initialization of a lazy proxy without accessing attributes. No-op for regular objects.

**Parameters:**

| Parameter | Type    | Default  | Description                   |
| --------- | ------- | -------- | ----------------------------- |
| `obj`   | `Any` | required | Lazy proxy or regular object. |

**Returns:** `None`

**Examples:**

```python
model = rc.instantiate(path=Path("config.yaml"), lazy=True)
rc.force_initialize(obj=model)  # model.__init__ called now
print(rc.is_lazy_proxy(obj=model))  # False
```

### `rc.to_dict(path, *, overrides=None, cli_overrides=None, exclude_markers=False)`

Export resolved config as a Python dictionary.

**Parameters:**

| Parameter           | Type                      | Default   | Description                                                                                 |
| ------------------- | ------------------------- | --------- | ------------------------------------------------------------------------------------------- |
| `path`            | `StrOrPath`             | required  | Path to config file. Accepts str, Path, or any os.PathLike.                                 |
| `overrides`       | `dict[str, Any] \| None` | `None`  | Dictionary of config overrides.                                                             |
| `cli_overrides` | `bool \| None` | `None` | Parse CLI overrides and `--help` from `sys.argv`. `None` uses `rc.set_cli_overrides()` (off by default). |
| `exclude_markers` | `bool`                  | `False` | If `True`, remove internal markers (`_target_`, `_ref_`, `_instance_`, `_lazy_`). |

**Returns:** `dict[str, Any]` - Resolved config as a dictionary

String values are [converted](type-coercion.md) to the declared field types, as in `rc.instantiate()`; values that cannot be converted are exported unchanged. The same applies to `to_yaml()`, `to_json()`, `to_toml()`, `to_file()`, `to_files()` and `export()`.

**Examples:**

```python
config = rc.to_dict(path=Path("config.yaml"))
clean = rc.to_dict(path=Path("config.yaml"), exclude_markers=True)
```

### `rc.to_yaml(path, *, overrides=None, cli_overrides=None, exclude_markers=False)`

Export resolved config as a YAML string.

**Parameters:**

| Parameter           | Type                      | Default   | Description                           |
| ------------------- | ------------------------- | --------- | ------------------------------------- |
| `path`            | `StrOrPath`             | required  | Path to config file. Accepts str, Path, or any os.PathLike. |
| `overrides`       | `dict[str, Any] \| None` | `None`  | Dictionary of config overrides.       |
| `cli_overrides` | `bool \| None` | `None` | Parse CLI overrides and `--help` from `sys.argv`. `None` uses `rc.set_cli_overrides()` (off by default). |
| `exclude_markers` | `bool`                  | `False` | If `True`, remove internal markers. |

**Returns:** `str` - Resolved config as a YAML string

**Examples:**

```python
yaml_str = rc.to_yaml(path=Path("config.yaml"))
```

### `rc.to_json(path, *, overrides=None, cli_overrides=None, exclude_markers=False, indent=2)`

Export resolved config as a JSON string.

**Parameters:**

| Parameter           | Type                      | Default   | Description                                                   |
| ------------------- | ------------------------- | --------- | ------------------------------------------------------------- |
| `path`            | `StrOrPath`             | required  | Path to config file. Accepts str, Path, or any os.PathLike.   |
| `overrides`       | `dict[str, Any] \| None` | `None`  | Dictionary of config overrides.                               |
| `cli_overrides` | `bool \| None` | `None` | Parse CLI overrides and `--help` from `sys.argv`. `None` uses `rc.set_cli_overrides()` (off by default). |
| `exclude_markers` | `bool`                  | `False` | If `True`, remove internal markers.                         |
| `indent`          | `int \| None`            | `2`     | Number of spaces for indentation.`None` for compact output. |

**Returns:** `str` - Resolved config as a JSON string

**Examples:**

```python
json_str = rc.to_json(path=Path("config.yaml"))
compact = rc.to_json(path=Path("config.yaml"), indent=None)
```

### `rc.to_toml(path, *, overrides=None, cli_overrides=None, exclude_markers=False)`

Export resolved config as a TOML string.

**Parameters:**

| Parameter           | Type                      | Default   | Description                           |
| ------------------- | ------------------------- | --------- | ------------------------------------- |
| `path`            | `StrOrPath`             | required  | Path to config file. Accepts str, Path, or any os.PathLike. |
| `overrides`       | `dict[str, Any] \| None` | `None`  | Dictionary of config overrides.       |
| `cli_overrides` | `bool \| None` | `None` | Parse CLI overrides and `--help` from `sys.argv`. `None` uses `rc.set_cli_overrides()` (off by default). |
| `exclude_markers` | `bool`                  | `False` | If `True`, remove internal markers. |

**Returns:** `str` - Resolved config as a TOML string

**Examples:**

```python
toml_str = rc.to_toml(path=Path("config.yaml"))
```

### `rc.to_file(source, output_path, *, overrides=None, cli_overrides=None, exclude_markers=False)`

Export config to a single file with format auto-detected from output path extension.

**Parameters:**

| Parameter           | Type                            | Default   | Description                                                                      |
| ------------------- | ------------------------------- | --------- | -------------------------------------------------------------------------------- |
| `source`          | `StrOrPath \| dict[str, Any]` | required  | Path to config file, or dict. Accepts str, Path, or any os.PathLike.             |
| `output_path`     | `StrOrPath`                   | required  | Output file path. Extension determines format (`.yaml`, `.json`, `.toml`). |
| `overrides`       | `dict[str, Any] \| None` | `None`  | Config overrides. Ignored if source is dict.                                     |
| `cli_overrides` | `bool \| None` | `None` | Parse CLI overrides and `--help` from `sys.argv`. `None` uses `rc.set_cli_overrides()` (off by default). Ignored if source is dict. |
| `exclude_markers` | `bool`                  | `False` | If `True`, remove internal markers.                                            |

**Returns:** `None`

**Raises:**

| Exception           | Condition                           |
| ------------------- | ----------------------------------- |
| `ConfigFileError` | Output file extension not supported |

**Examples:**

```python
# From file path
rc.to_file(source=Path("config.yaml"), output_path=Path("output.json"))

# From dict
config = {"model": {"lr": 0.01}, "epochs": 10}
rc.to_file(source=config, output_path=Path("output.yaml"))
```

### `rc.to_files(source, config_root_file, *, overrides=None, cli_overrides=None, exclude_markers=False)`

Export config preserving file structure (with `_ref_` relationships).

**Parameters:**

| Parameter            | Type                            | Default   | Description                                              |
| -------------------- | ------------------------------- | --------- | -------------------------------------------------------- |
| `source`           | `StrOrPath \| dict[str, Any]` | required  | Path to config file, or dict. Accepts str, Path, or any os.PathLike. |
| `config_root_file` | `StrOrPath`                   | required  | Output root file path. Extension determines root format. |
| `overrides`        | `dict[str, Any] \| None` | `None`  | Config overrides. Ignored if source is dict.             |
| `cli_overrides` | `bool \| None` | `None` | Parse CLI overrides and `--help` from `sys.argv`. `None` uses `rc.set_cli_overrides()` (off by default). Ignored if source is dict. |
| `exclude_markers`  | `bool`                  | `False` | If `True`, remove internal markers.                    |

**Returns:** `None`

**Behavior:**

- Root file format determined by `config_root_file` extension
- Referenced files preserve their original formats
- When source is dict, only root file is written

**Examples:**

```python
rc.to_files(source=Path("trainer.yaml"), config_root_file=Path("output/trainer.json"))
# Creates:
#   output/trainer.json (root in JSON)
#   output/models/resnet.yaml (preserves YAML)
```

### `rc.export(path, exporter, *, overrides=None, cli_overrides=None)`

Export resolved config using a custom exporter.

**Parameters:**

| Parameter         | Type                      | Default  | Description                     |
| ----------------- | ------------------------- | -------- | ------------------------------- |
| `path`          | `StrOrPath`             | required | Path to config file. Accepts str, Path, or any os.PathLike. |
| `exporter`      | `Exporter`              | required | Exporter instance to use.       |
| `overrides`     | `dict[str, Any] \| None` | `None` | Dictionary of config overrides. |
| `cli_overrides` | `bool \| None` | `None` | Parse CLI overrides and `--help` from `sys.argv`. `None` uses `rc.set_cli_overrides()` (off by default). |

**Returns:** The exported data in the exporter's target format

**Examples:**

```python
class MyExporter(Exporter):
    def export(self, config: dict) -> str:
        return json.dumps(config)

result = rc.export(path=Path("config.yaml"), exporter=MyExporter())
```

### `@rc.resolver(*path)`

Decorator to register a resolver function for use in interpolation expressions.

**Parameters:**

| Parameter | Type    | Default  | Description                                                                                                                         |
| --------- | ------- | -------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `*path` | `str` | required | Path components. Accepts multiple arguments (`"db", "lookup"`) or a single delimited string (`"db:lookup"` or `"db.lookup"`). |

**Returns:** Decorator function

**Special Parameters (in decorated function):**

- `_config_` (`dict`): Keyword-only parameter that receives read-only view of current config

**Examples:**

```python
# All equivalent ways to register "db:lookup":
@rc.resolver("db", "lookup")
def lookup1(table: str, id: int) -> dict:
    return database.get(table, id)

@rc.resolver("db:lookup")
def lookup2(table: str, id: int) -> dict:
    return database.get(table, id)

@rc.resolver("db.lookup")
def lookup3(table: str, id: int) -> dict:
    return database.get(table, id)

# Simple resolver
@rc.resolver("uuid")
def gen_uuid() -> str:
    import uuid
    return str(uuid.uuid4())

# Resolver with config access
@rc.resolver("derive")
def derive(path: str, *, _config_: dict) -> Any:
    return _config_.get(path)
```

### `rc.register_resolver(*path, func)`

Register a custom resolver function for use in interpolation expressions.

**Parameters:**

| Parameter | Type                   | Default  | Description                                                                                                                         |
| --------- | ---------------------- | -------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `*path` | `str`                | required | Path components. Accepts multiple arguments (`"db", "lookup"`) or a single delimited string (`"db:lookup"` or `"db.lookup"`). |
| `func`  | `Callable[..., Any]` | required | The resolver function to register.                                                                                                  |

**Returns:** `None`

**Raises:**

| Exception      | Condition                                |
| -------------- | ---------------------------------------- |
| `ValueError` | If path is empty or func is not callable |

**Examples:**

```python
def gen_uuid() -> str:
    import uuid
    return str(uuid.uuid4())

# All equivalent:
rc.register_resolver("uuid", func=gen_uuid)
rc.register_resolver("db", "lookup", func=my_lookup)
rc.register_resolver("db:lookup", func=my_lookup)
rc.register_resolver("db.lookup", func=my_lookup)
```

### `rc.unregister_resolver(*path)`

Unregister a previously registered resolver.

**Parameters:**

| Parameter | Type    | Default  | Description                                                                                                                         |
| --------- | ------- | -------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `*path` | `str` | required | Path components. Accepts multiple arguments (`"db", "lookup"`) or a single delimited string (`"db:lookup"` or `"db.lookup"`). |

**Returns:** `None`

**Raises:**

| Exception    | Condition                         |
| ------------ | --------------------------------- |
| `KeyError` | No resolver with that path exists |

**Examples:**

```python
rc.unregister_resolver("uuid")

# All equivalent ways to unregister "db:lookup":
rc.unregister_resolver("db", "lookup")
rc.unregister_resolver("db:lookup")
rc.unregister_resolver("db.lookup")
```

### `rc.set_cli_overrides(enabled)`

Set whether config loading reads `sys.argv` by default. When enabled, `key=value` arguments are applied as overrides and `--help`/`-h` shows config help. CLI overrides are **disabled by default**, so loading config inside a web app, worker, or test run never touches the host program's command line. A per-call `cli_overrides=True`/`False` argument takes precedence over this setting. Thread-safe.

**Parameters:**

| Parameter | Type   | Default  | Description                                                     |
| --------- | ------ | -------- | --------------------------------------------------------------- |
| `enabled` | `bool` | required | `True` to read CLI overrides by default, `False` to ignore `sys.argv`. |

**Returns:** `None`

**Examples:**

```python
# At the start of a training script
rc.set_cli_overrides(True)
model = rc.instantiate(path="config.yaml")  # python train.py model.lr=0.01
```

See [Embedding in Applications](embedding.md) for when to enable it.

### `rc.cli_overrides_enabled()`

Return whether config loading reads `sys.argv` by default. Thread-safe.

**Parameters:** None

**Returns:** `bool` - The process-wide setting from `rc.set_cli_overrides()` (`False` initially).

**Examples:**

```python
print(rc.cli_overrides_enabled())  # False
rc.set_cli_overrides(True)
print(rc.cli_overrides_enabled())  # True
```

### `rc.set_help_integration(integration)`

Set a custom help integration for CLI help display.

**Parameters:**

| Parameter     | Type              | Default  | Description                        |
| ------------- | ----------------- | -------- | ---------------------------------- |
| `integration` | `HelpIntegration` | required | A HelpIntegration instance to use. |

**Returns:** `None`

**Raises:**

| Exception      | Condition               |
| -------------- | ----------------------- |
| `ValueError` | If integration is None. |

**Examples:**

```python
from rconfig import GroupedHelpIntegration

rc.set_help_integration(GroupedHelpIntegration())
```

### `rc.current_help_integration()`

Get the current help integration.

**Parameters:** None

**Returns:** `HelpIntegration` - The current integration (default: `FlatHelpIntegration`)

**Examples:**

```python
integration = rc.current_help_integration()
print(type(integration))  # <class 'rconfig.help.FlatHelpIntegration'>
```

### `@rc.help_integration`

Decorator to register a function as the help integration.

The decorated function receives `(provenance, config_path)` and is responsible for all behavior including calling `sys.exit()` if needed.

**Parameters:**

| Parameter | Type                                | Default  | Description                      |
| --------- | ----------------------------------- | -------- | -------------------------------- |
| `func`  | `Callable[[Provenance, str], None]` | required | Function to handle help display. |

**Returns:** The same function (for use as decorator)

**Examples:**

```python
@rc.help_integration
def my_help(provenance, config_path):
    print(f"Help for {config_path}")
    for path, entry in provenance.items():
        print(f"  {path}: {entry.type_hint}")
    sys.exit(0)
```

### `@rc.on_config_loaded(*, pattern=None, priority=50)`

Decorator to register a hook called after config composition, before instantiation.

Hooks can optionally return a `dict` to modify the config. If a hook returns `None` (or doesn't return), the config is unchanged. Multiple hooks chain modifications in priority order.

**Parameters:**

| Parameter  | Type           | Default  | Description                                      |
| ---------- | -------------- | -------- | ------------------------------------------------ |
| `pattern`  | `str \| None`  | `None`   | Glob pattern for conditional execution.          |
| `priority` | `int`          | `50`     | Execution order (lower values run first).        |

**Returns:** The decorated function.

**Examples:**

```python
from rconfig.hooks import HookContext

@rc.on_config_loaded
def validate_paths(ctx: HookContext) -> None:
    """Validate data paths exist."""
    if ctx.config and "data_path" in ctx.config:
        path = Path(ctx.config["data_path"])
        if not path.exists():
            raise ValueError(f"Data path not found: {path}")

@rc.on_config_loaded(pattern="**/model/*.yaml", priority=10)
def model_hook(ctx: HookContext) -> None:
    """Only runs for model configs, runs early."""
    ...

@rc.on_config_loaded
def inject_secrets(ctx: HookContext) -> dict | None:
    """Modify config by returning a new dict."""
    if ctx.config.get("api_key") == "_required_":
        return {**ctx.config, "api_key": os.getenv("API_KEY")}
    return None  # No changes
```

### `@rc.on_before_instantiate(*, pattern=None, priority=50)`

Decorator to register a hook called before each object's constructor.

**Parameters:**

| Parameter  | Type           | Default  | Description                                      |
| ---------- | -------------- | -------- | ------------------------------------------------ |
| `pattern`  | `str \| None`  | `None`   | Glob pattern for conditional execution.          |
| `priority` | `int`          | `50`     | Execution order (lower values run first).        |

**Returns:** The decorated function.

**Examples:**

```python
@rc.on_before_instantiate
def log_instantiation(ctx: HookContext) -> None:
    print(f"Creating {ctx.target_name} at {ctx.inner_path}")
```

### `@rc.on_after_instantiate(*, pattern=None, priority=50)`

Decorator to register a hook called after each object's constructor returns.

**Parameters:**

| Parameter  | Type           | Default  | Description                                      |
| ---------- | -------------- | -------- | ------------------------------------------------ |
| `pattern`  | `str \| None`  | `None`   | Glob pattern for conditional execution.          |
| `priority` | `int`          | `50`     | Execution order (lower values run first).        |

**Returns:** The decorated function.

**Examples:**

```python
@rc.on_after_instantiate
def register_metrics(ctx: HookContext) -> None:
    metrics.register(ctx.target_name, ctx.instance)
```

### `@rc.on_error(*, pattern=None, priority=50)`

Decorator to register a hook called when instantiation fails.

**Parameters:**

| Parameter  | Type           | Default  | Description                                      |
| ---------- | -------------- | -------- | ------------------------------------------------ |
| `pattern`  | `str \| None`  | `None`   | Glob pattern for conditional execution.          |
| `priority` | `int`          | `50`     | Execution order (lower values run first).        |

**Returns:** The decorated function.

**Examples:**

```python
@rc.on_error
def log_failures(ctx: HookContext) -> None:
    logger.error(f"Instantiation failed: {ctx.error}")
```

### `rc.register_hook(phase, func, *, name=None, pattern=None, priority=50)`

Explicitly register a hook function for a specific phase.

**Parameters:**

| Parameter  | Type           | Default     | Description                                      |
| ---------- | -------------- | ----------- | ------------------------------------------------ |
| `phase`    | `HookPhase`    | required    | The lifecycle phase to register for.             |
| `func`     | `Callable`     | required    | The hook function.                               |
| `name`     | `str \| None`  | `None`      | Hook name (defaults to function name).           |
| `pattern`  | `str \| None`  | `None`      | Glob pattern for conditional execution.          |
| `priority` | `int`          | `50`        | Execution order (lower values run first).        |

**Returns:** `None`

**Examples:**

```python
from rconfig.hooks import HookPhase

def my_hook(ctx: HookContext) -> None:
    print(f"Config loaded: {ctx.config_path}")

rc.register_hook(HookPhase.CONFIG_LOADED, my_hook, name="my_hook")
```

### `rc.unregister_hook(name, *, phase=None)`

Remove a registered hook by name.

**Parameters:**

| Parameter | Type              | Default  | Description                                        |
| --------- | ----------------- | -------- | -------------------------------------------------- |
| `name`    | `str`             | required | Name of the hook to remove.                        |
| `phase`   | `HookPhase \| None` | `None`   | If specified, only remove from this phase.         |

**Returns:** `None`

**Raises:**

| Exception    | Condition                        |
| ------------ | -------------------------------- |
| `KeyError`   | If no hook with that name exists |

**Examples:**

```python
rc.unregister_hook("my_hook")
rc.unregister_hook("my_hook", phase=HookPhase.CONFIG_LOADED)
```

### `rc.register_callback(callback)`

Register a Callback class instance. All implemented methods are registered as hooks.

**Parameters:**

| Parameter  | Type         | Default  | Description                     |
| ---------- | ------------ | -------- | ------------------------------- |
| `callback` | `Callback`   | required | Instance of a Callback subclass |

**Returns:** `None`

**Examples:**

```python
class ExperimentTracker(rc.Callback):
    def on_config_loaded(self, ctx: HookContext) -> None:
        self.run_id = start_run()
        log_config(self.run_id, dict(ctx.config))

    def on_after_instantiate(self, ctx: HookContext) -> None:
        log_component(self.run_id, ctx.target_name)

tracker = ExperimentTracker()
rc.register_callback(tracker)
```

### `rc.unregister_callback(callback)`

Remove all hooks registered by a Callback instance.

**Parameters:**

| Parameter  | Type         | Default  | Description                     |
| ---------- | ------------ | -------- | ------------------------------- |
| `callback` | `Callback`   | required | The Callback instance to remove |

**Returns:** `None`

**Examples:**

```python
rc.unregister_callback(tracker)
```

### `rc.known_hooks()`

Return a read-only view of all registered hooks.

**Parameters:** None

**Returns:** `MappingProxyType[HookPhase, tuple[HookEntry, ...]]`

**Examples:**

```python
for phase, hooks in rc.known_hooks().items():
    for hook in hooks:
        print(f"{phase.name}: {hook.name} (priority={hook.priority})")
```

---

## Common Types

Types returned by common API functions.

### `ValidationResult`

Result of config validation, returned by `rc.validate()`.

**Attributes:**

| Attribute | Type                     | Description                                        |
| --------- | ------------------------ | -------------------------------------------------- |
| `valid` | `bool`                   | `True` if validation passed with no errors       |
| `errors`| `list[ValidationError]`  | List of validation errors (empty if `valid=True`) |

**Examples:**

```python
result = rc.validate(path="config.yaml")
if not result.valid:
    for error in result.errors:
        print(error)
```

### `ConfigDiff`

Immutable diff result, returned by `rc.diff()`. Acts as a mapping of config paths to `DiffEntry` objects.

**Attributes:**

| Attribute     | Type                              | Description                      |
| ------------- | --------------------------------- | -------------------------------- |
| `added`     | `MappingProxyType[str, DiffEntry]` | Entries present only in right    |
| `removed`   | `MappingProxyType[str, DiffEntry]` | Entries present only in left     |
| `changed`   | `MappingProxyType[str, DiffEntry]` | Entries with different values    |
| `unchanged` | `MappingProxyType[str, DiffEntry]` | Entries with identical values    |

**Methods:**

| Method          | Returns          | Description                         |
| --------------- | ---------------- | ----------------------------------- |
| `is_empty()`  | `bool`         | True if no added/removed/changed    |
| `to_dict()`   | `dict[str, Any]` | Export as dictionary                |
| `__len__()`   | `int`          | Total entry count                   |
| `__contains__(path)` | `bool`  | Check if path exists in diff        |
| `__getitem__(path)` | `DiffEntry` | Get entry by config path           |

### `DiffEntry`

A single entry in a ConfigDiff.

**Attributes:**

| Attribute            | Type                      | Description                                              |
| -------------------- | ------------------------- | -------------------------------------------------------- |
| `path`             | `str`                   | Config path (e.g., "model.lr")                           |
| `diff_type`        | `DiffEntryType`         | One of: `ADDED`, `REMOVED`, `CHANGED`, `UNCHANGED`      |
| `left_value`       | `Any`                   | Value in left config (`None` if added)                   |
| `right_value`      | `Any`                   | Value in right config (`None` if removed)                |
| `left_provenance`  | `ProvenanceEntry \| None` | Provenance entry from left config                        |
| `right_provenance` | `ProvenanceEntry \| None` | Provenance entry from right config                       |

### `ProvenanceNode`

Immutable node in a provenance trace tree, returned by `prov.trace(path)`. Forms a tree structure for tracing compound expressions through refs, interpolations, operators, and resolvers.

**Attributes:**

| Attribute         | Type                          | Description                                          |
| ----------------- | ----------------------------- | ---------------------------------------------------- |
| `source_type`   | `NodeSourceType`              | Type of this node (file, ref, interpolation, etc.)   |
| `path`          | `str \| None`                  | Config path (e.g., "/model.lr")                      |
| `file`          | `str \| None`                  | Source file name                                     |
| `line`          | `int \| None`                  | Line number in source file                           |
| `value`         | `Any`                         | The resolved value at this node                      |
| `expression`    | `str \| None`                  | Interpolation expression (e.g., "${/a + /b}")        |
| `operator`      | `str \| None`                  | Operator for compound expressions (+, *, etc.)       |
| `env_var`       | `str \| None`                  | Environment variable name (for env sources)          |
| `cli_arg`       | `str \| None`                  | CLI argument (for CLI sources)                       |
| `resolver_name` | `str \| None`                  | Resolver path (e.g., "uuid", "db:lookup")            |
| `resolver_func` | `str \| None`                  | Function name of the resolver                        |
| `resolver_module`| `str \| None`                 | Module where the resolver is defined                 |
| `children`      | `tuple[ProvenanceNode, ...]`  | Child nodes in the tree                              |

**Methods:**

| Method       | Returns          | Description                                |
| ------------ | ---------------- | ------------------------------------------ |
| `to_dict()` | `dict[str, Any]` | Recursively convert to dictionary          |

**Examples:**

```python
prov = rc.get_provenance(path="config.yaml")
tree = prov.trace("model.lr")
if tree:
    print(tree.source_type)  # "file", "interpolation", etc.
    print(tree.file, tree.line)
    for child in tree.children:
        print(f"  {child.source_type}: {child.path}")
    # Export as dict
    data = tree.to_dict()
```

### `NodeSourceType`

Enum (`StrEnum`) indicating the type of each node in a provenance trace tree.

**Values:**

| Value             | Description                                       |
| ----------------- | ------------------------------------------------- |
| `FILE`          | Value came from a config file                     |
| `REF`           | Value came from a `_ref_` reference             |
| `INSTANCE`      | Value came from an instance chain                 |
| `INTERPOLATION` | Value was computed via interpolation              |
| `CLI`           | Value was set via command-line argument            |
| `ENV`           | Value was set via environment variable             |
| `PROGRAMMATIC`  | Value was set programmatically                    |
| `OPERATOR`      | Value is result of an operator expression         |
| `RESOLVER`      | Value came from a resolver function               |

---

## Advanced API

Classes and types for extending and customizing rconfig. Use these when you need to create custom loaders, exporters, or help integrations.

### Multirun Types

#### `MultirunResult`

Result of a single multirun instantiation. Contains the immutable resolved config, the specific overrides applied for this run, and the instantiated object (or stored error).

**Attributes:**

| Attribute   | Type                         | Description                           |
| ----------- | ---------------------------- | ------------------------------------- |
| `config`  | `MappingProxyType[str, Any]` | Immutable view of the resolved config |
| `overrides` | `MappingProxyType[str, Any]` | The specific overrides for this run   |
| `instance` | `T`                          | The instantiated object (property)    |

**Notes:**

- `instance` is a property that raises any stored error when accessed
- Use try/except for graceful error handling per run

**Examples:**

```python
for result in rc.instantiate_multirun(...):
    # Fail fast - raises if this run failed
    train(result.instance)

    # Or handle errors individually
    try:
        train(result.instance)
    except (ValidationError, InstantiationError) as e:
        log_failure(result.overrides, e)
```

#### `MultirunIterator`

Lazy iterator with length and slicing support for multirun results. Enables efficient iteration with progress tracking.

**Methods:**

| Method            | Returns               | Description                   |
| ----------------- | --------------------- | ----------------------------- |
| `__len__()`     | `int`               | Total number of runs          |
| `__iter__()`    | `MultirunIterator[T]` | Fresh iterator from beginning |
| `__reversed__()` | `MultirunIterator[T]` | Iterator in reverse order     |
| `__getitem__(i)` | `MultirunResult[T]`  | Access single run by index    |
| `__getitem__(s)` | `MultirunIterator[T]` | Slice to get subset iterator  |

**Examples:**

```python
results = rc.instantiate_multirun(...)

# Progress tracking with tqdm
for result in tqdm(results):
    train(result.instance)

# Resume from crash point
for result in results[50:]:
    train(result.instance)

# Distribute across workers
worker1_results = results[0:25]
worker2_results = results[25:50]

# Debug specific run
single_result = results[3]
```

#### `MULTIRUN_HELP`

Help text constant for multirun CLI options. Use this to include multirun documentation in your CLI help.

**Type:** `str`

**Example:**

```python
import argparse
from rconfig import MULTIRUN_HELP

parser = argparse.ArgumentParser(
    epilog=MULTIRUN_HELP,
    formatter_class=argparse.RawDescriptionHelpFormatter
)
```

#### `MultirunError`

Base exception for multirun-related errors.

#### `InvalidSweepValueError`

Raised when sweep values are not lists.

#### `NoRunConfigurationError`

Raised when neither `sweep` nor `experiments` is provided to `instantiate_multirun()`.

### Help Integration Classes

#### `HelpIntegration`

Abstract base class for CLI help integrations. Subclass this to customize how config help is integrated into CLI.

**Constructor:**

| Parameter            | Type   | Default | Description                               |
| -------------------- | ------ | ------- | ----------------------------------------- |
| `consume_help_flag` | `bool` | `True` | If True, remove --help/-h from sys.argv. |

**Abstract Methods:**

| Method                                   | Description                          |
| ---------------------------------------- | ------------------------------------ |
| `integrate(provenance, config_path)` | Called when --help/-h is detected. |

**Examples:**

```python
from rconfig import HelpIntegration

class CustomHelpIntegration(HelpIntegration):
    def integrate(self, provenance, config_path):
        print(f"Custom help for {config_path}")
        for path, entry in provenance.items():
            print(f"  {path}: {entry.value}")
        sys.exit(0)

rc.set_help_integration(CustomHelpIntegration())
```

#### `FlatHelpIntegration`

Displays config entries as a flat aligned table. This is the default integration.

**Constructor:**

| Parameter | Type             | Default      | Description       |
| --------- | ---------------- | ------------ | ----------------- |
| `output` | `TextIO \| None` | `sys.stdout` | Output stream.    |

**Output format:**

```
Configuration options for config.yaml
=====================================

model.lr              float       0.001      Learning rate
model.hidden_size     int         256        Hidden layer size
data.path             str         (required) Path to data
```

#### `GroupedHelpIntegration`

Displays config entries grouped by top-level key with indentation.

**Constructor:**

| Parameter | Type             | Default      | Description    |
| --------- | ---------------- | ------------ | -------------- |
| `output` | `TextIO \| None` | `sys.stdout` | Output stream. |

**Output format:**

```
Configuration options for config.yaml
=====================================

model:
  lr                  float       0.001      Learning rate
  hidden_size         int         256        Hidden layer size
data:
  path                str         (required) Path to data
```

**Examples:**

```python
from rconfig import GroupedHelpIntegration

rc.set_help_integration(GroupedHelpIntegration())
```

#### `ArgparseHelpIntegration`

Integrates config entries into argparse help output. Adds config entries to the parser's epilog.

**Constructor:**

| Parameter | Type                       | Default  | Description                       |
| --------- | -------------------------- | -------- | --------------------------------- |
| `parser` | `argparse.ArgumentParser` | required | The argparse parser to integrate. |

**Notes:**

- Uses `consume_help_flag=False` because argparse handles --help itself

**Examples:**

```python
import argparse
from rconfig import ArgparseHelpIntegration

parser = argparse.ArgumentParser()
parser.add_argument("--verbose", action="store_true")

rc.set_help_integration(ArgparseHelpIntegration(parser))
args = parser.parse_args()
config = rc.instantiate(Path("config.yaml"))
```

### Exporter Registry

#### `rc.register_exporter(exporter, *extensions)`

Register an exporter for specific file extensions.

**Parameters:**

| Parameter       | Type       | Default  | Description                                              |
| --------------- | ---------- | -------- | -------------------------------------------------------- |
| `exporter`    | `Exporter` | required | Exporter instance to register.                           |
| `*extensions` | `str`    | required | Extensions to register (e.g., `".xml"`, `".protobuf"`). |

**Returns:** `None`

**Examples:**

```python
class XmlExporter(Exporter):
    def export(self, config: dict) -> str:
        return dict_to_xml(config)

rc.register_exporter(XmlExporter(), ".xml")
```

#### `rc.unregister_exporter(extension)`

Unregister an exporter by extension.

**Parameters:**

| Parameter   | Type  | Default  | Description                  |
| ----------- | ----- | -------- | ---------------------------- |
| `extension` | `str` | required | The extension to unregister. |

**Returns:** `None`

**Raises:**

| Exception  | Condition                |
| ---------- | ------------------------ |
| `KeyError` | Extension not registered |

**Examples:**

```python
rc.unregister_exporter(extension=".xml")
```

#### `rc.get_exporter(path)`

Get the appropriate exporter for a config file based on its extension.

**Parameters:**

| Parameter | Type        | Default  | Description              |
| --------- | ----------- | -------- | ------------------------ |
| `path`  | `StrOrPath` | required | Path to the config file. Accepts str, Path, or any os.PathLike. |

**Returns:** `Exporter` - An exporter instance for the file format

**Raises:**

| Exception         | Condition                                |
| ----------------- | ---------------------------------------- |
| `ConfigFileError` | If no exporter supports the file format. |

**Examples:**

```python
exporter = rc.get_exporter(Path("config.yaml"))
result = exporter.export(config_dict)
```

#### `rc.supported_exporter_extensions()`

Get all supported export file extensions.

**Parameters:** None

**Returns:** `frozenset[str]` - Supported extensions (lowercase, e.g., `{'.yaml', '.json', '.toml'}`)

**Examples:**

```python
extensions = rc.supported_exporter_extensions()
# frozenset({'.yaml', '.yml', '.json', '.toml'})
```

### Exporter Classes

#### `Exporter`

Abstract base class for config exporters. Subclass this to create custom exporters.

**Abstract Methods:**

| Method                       | Returns | Description                        |
| ---------------------------- | ------- | ---------------------------------- |
| `export(config: dict)` | `Any` | Export config to the target format |

**Examples:**

```python
from rconfig import Exporter

class XmlExporter(Exporter):
    def export(self, config: dict) -> str:
        return dict_to_xml(config)

rc.register_exporter(XmlExporter(), ".xml")
```

#### `YamlExporter`

Export config as a YAML string.

**Constructor:**

| Parameter            | Type               | Default   | Description                       |
| -------------------- | ------------------ | --------- | --------------------------------- |
| `default_flow_style` | `bool \| None`      | `False` | None=block, True=flow, False=mixed |
| `indent`           | `int`              | `2`     | Indentation spaces                |
| `exclude_markers`  | `bool`             | `False` | Remove internal markers           |
| `markers`          | `tuple[str, ...]` | (default) | Marker keys to exclude            |

#### `JsonExporter`

Export config as a JSON string.

**Constructor:**

| Parameter           | Type               | Default   | Description                     |
| ------------------- | ------------------ | --------- | ------------------------------- |
| `indent`          | `int \| None`       | `2`     | Indentation (None for compact)  |
| `ensure_ascii`    | `bool`             | `False` | Escape non-ASCII characters     |
| `sort_keys`       | `bool`             | `False` | Sort dictionary keys            |
| `exclude_markers` | `bool`             | `False` | Remove internal markers         |
| `markers`         | `tuple[str, ...]` | (default) | Marker keys to exclude          |

#### `TomlExporter`

Export config as a TOML string.

**Constructor:**

| Parameter             | Type               | Default   | Description               |
| --------------------- | ------------------ | --------- | ------------------------- |
| `multiline_strings` | `bool`             | `False` | Use multiline for strings |
| `exclude_markers`   | `bool`             | `False` | Remove internal markers   |
| `markers`           | `tuple[str, ...]` | (default) | Marker keys to exclude    |

#### `DictExporter`

Export config as a Python dictionary. This is the base exporter used internally.

#### `FileExporter`

Base class for file-based exporters. Subclass this to create exporters that write to files.

#### `SingleFileExporter`

Export config to a single file. Used by `rc.to_file()`.

#### `MultiFileExporter`

Export config preserving `_ref_` structure across multiple files. Used by `rc.to_files()`.

### Loader Registry

#### `rc.register_loader(loader, *extensions)`

Register a config file loader for specific extensions.

**Parameters:**

| Parameter       | Type               | Default  | Description                                          |
| --------------- | ------------------ | -------- | ---------------------------------------------------- |
| `loader`      | `ConfigFileLoader` | required | A `ConfigFileLoader` instance to register.           |
| `*extensions` | `str`            | required | Extensions to register (e.g., `".ini"`, `".conf"`). |

**Returns:** `None`

**Examples:**

```python
class IniConfigLoader(ConfigFileLoader):
    def load(self, path: Path) -> dict[str, Any]:
        import configparser
        parser = configparser.ConfigParser()
        parser.read(path)
        return {s: dict(parser[s]) for s in parser.sections()}

    def load_with_positions(self, path: Path) -> PositionMap:
        return PositionMap(self.load(path))

rc.register_loader(IniConfigLoader(), ".ini")
```

#### `rc.unregister_loader(extension)`

Unregister a config file loader by extension.

**Parameters:**

| Parameter   | Type  | Default  | Description                  |
| ----------- | ----- | -------- | ---------------------------- |
| `extension` | `str` | required | The extension to unregister. |

**Returns:** `None`

**Raises:**

| Exception  | Condition                |
| ---------- | ------------------------ |
| `KeyError` | Extension not registered |

**Examples:**

```python
rc.unregister_loader(extension=".ini")
```

#### `rc.get_loader(path)`

Get the appropriate loader for a config file based on its extension.

**Parameters:**

| Parameter | Type        | Default  | Description              |
| --------- | ----------- | -------- | ------------------------ |
| `path`  | `StrOrPath` | required | Path to the config file. Accepts str, Path, or any os.PathLike. |

**Returns:** `ConfigFileLoader` - A loader instance for the file format

**Raises:**

| Exception         | Condition                              |
| ----------------- | -------------------------------------- |
| `ConfigFileError` | If no loader supports the file format. |

**Examples:**

```python
loader = rc.get_loader(Path("config.yaml"))
config_dict = loader.load(Path("config.yaml"))
```

#### `rc.supported_loader_extensions()`

Get all supported loader file extensions.

**Parameters:** None

**Returns:** `frozenset[str]` - Supported extensions (lowercase, e.g., `{'.yaml', '.yml', '.json', '.toml'}`)

**Examples:**

```python
extensions = rc.supported_loader_extensions()
```

### Loader Classes

#### `ConfigFileLoader`

Abstract base class for config file loaders. Subclass this to support additional file formats.

**Abstract Methods:**

| Method                          | Returns       | Description                            |
| ------------------------------- | ------------- | -------------------------------------- |
| `load(path: Path)`            | `dict`      | Load config as dictionary              |
| `load_with_positions(path)` | `PositionMap` | Load with line/column position info    |

**Examples:**

```python
from rconfig import ConfigFileLoader

class IniConfigLoader(ConfigFileLoader):
    def load(self, path: Path) -> dict:
        import configparser
        parser = configparser.ConfigParser()
        parser.read(path)
        return {s: dict(parser[s]) for s in parser.sections()}

    def load_with_positions(self, path: Path) -> PositionMap:
        return PositionMap(self.load(path))

rc.register_loader(IniConfigLoader(), ".ini")
```

#### `YamlConfigLoader`

Load YAML config files using ruamel.yaml.

**Supported Extensions:** `.yaml`, `.yml`

#### `JsonConfigLoader`

Load JSON config files using Python's standard library.

**Supported Extensions:** `.json`

#### `TomlConfigLoader`

Load TOML config files using Python 3.11+ tomllib.

**Supported Extensions:** `.toml`

### Deprecation Classes

#### `DeprecationInfo`

Information about a deprecated key.

**Attributes:**

| Attribute    | Type           | Description                           |
| ------------ | -------------- | ------------------------------------- |
| `old_key`  | `str`        | The deprecated key path               |
| `new_key`  | `str \| None` | Migration target (if any)             |
| `message`  | `str \| None` | Custom deprecation message            |
| `remove_in` | `str \| None` | Version when key will be removed      |
| `policy`   | `str \| None` | Override policy (warn/error/ignore) |

#### `DeprecationHandler`

Abstract base class for custom deprecation warning handlers.

**Abstract Methods:**

| Method                                        | Description                     |
| --------------------------------------------- | ------------------------------- |
| `handle(info, path, file, line)` | Called when deprecated key used |

**Examples:**

```python
from rconfig import DeprecationHandler, DeprecationInfo

class LoggingHandler(DeprecationHandler):
    def handle(self, info: DeprecationInfo, path: str, file: str, line: int) -> None:
        import logging
        logging.warning(f"Deprecated key '{path}' at {file}:{line}")

rc.set_deprecation_handler(LoggingHandler())
```

#### `DeprecatedKeyError`

Exception raised when a deprecated key is used and the deprecation policy is set to `"error"`.

#### `RconfigDeprecationWarning`

Warning class used by the default deprecation handler. Integrates with Python's `warnings` filter system.

### Hook Classes

#### `rc.Callback`

Base class for class-based hooks that can maintain state across hook invocations.

**Methods to Override:**

| Method                         | Phase              | Description                          |
| ------------------------------ | ------------------ | ------------------------------------ |
| `on_config_loaded(ctx)`        | CONFIG_LOADED      | Called after config composition      |
| `on_before_instantiate(ctx)`   | BEFORE_INSTANTIATE | Called before each constructor       |
| `on_after_instantiate(ctx)`    | AFTER_INSTANTIATE  | Called after each constructor        |
| `on_error(ctx)`                | ON_ERROR           | Called when instantiation fails      |

**Examples:**

```python
class ExperimentTracker(rc.Callback):
    def __init__(self, tracking_uri: str):
        self.tracking_uri = tracking_uri
        self.run_id = None

    def on_config_loaded(self, ctx: HookContext) -> None:
        self.run_id = start_run(self.tracking_uri)
        log_config(self.run_id, dict(ctx.config))

    def on_after_instantiate(self, ctx: HookContext) -> None:
        log_component(self.run_id, ctx.target_name, ctx.instance)

    def on_error(self, ctx: HookContext) -> None:
        mark_failed(self.run_id, str(ctx.error))

tracker = ExperimentTracker("http://mlflow.internal")
rc.register_callback(tracker)
```

#### `HookPhase`

Enum defining the lifecycle phases where hooks can be registered.

**Values:**

| Value                | Description                                    |
| -------------------- | ---------------------------------------------- |
| `CONFIG_LOADED`      | After config composition, before instantiation |
| `BEFORE_INSTANTIATE` | Before each object's constructor call          |
| `AFTER_INSTANTIATE`  | After each object's constructor returns        |
| `ON_ERROR`           | When instantiation fails with an exception     |

#### `HookContext`

Immutable context object passed to hook functions.

**Attributes:**

| Attribute     | Type                        | Available In             | Description                    |
| ------------- | --------------------------- | ------------------------ | ------------------------------ |
| `phase`       | `HookPhase`                 | All                      | Current lifecycle phase        |
| `config_path` | `str`                       | All                      | Path to the config file        |
| `config`      | `MappingProxyType` or None  | All                      | Read-only view of config dict  |
| `inner_path`  | `str \| None`               | BEFORE/AFTER_INSTANTIATE | Path within config             |
| `target_name` | `str \| None`               | BEFORE/AFTER_INSTANTIATE | The `_target_` name            |
| `instance`    | `Any \| None`               | AFTER_INSTANTIATE        | The instantiated object        |
| `error`       | `Exception \| None`         | ON_ERROR                 | The exception that occurred    |

#### `HookEntry`

Immutable dataclass representing a registered hook.

**Attributes:**

| Attribute  | Type           | Description                               |
| ---------- | -------------- | ----------------------------------------- |
| `name`     | `str`          | Hook identifier                           |
| `phase`    | `HookPhase`    | Lifecycle phase                           |
| `func`     | `Callable`     | The hook function                         |
| `pattern`  | `str \| None`  | Glob pattern for conditional execution    |
| `priority` | `int`          | Execution order (lower runs first)        |

#### `HookError`

Base exception for hook-related errors.

#### `HookExecutionError`

Exception raised when a hook function raises an error during execution.

**Attributes:**

| Attribute        | Type           | Description                    |
| ---------------- | -------------- | ------------------------------ |
| `hook_name`      | `str`          | Name of the failing hook       |
| `phase`          | `HookPhase`    | Phase when error occurred      |
| `original_error` | `Exception`    | The original exception         |

### Error Classes

See [Error Handling](advanced-usage.md#error-handling) for the full exception hierarchy.

#### `ValueCoercionError`

Subclass of `TypeMismatchError` (and therefore `ValidationError`). Raised by `rc.instantiate()` and `rc.instantiate_multirun()` when a string value cannot be [converted](type-coercion.md) to the field's declared type. `rc.validate()` reports it in `ValidationResult.errors` instead of raising.

**Attributes:**

| Attribute           | Type              | Description                                                                 |
| ------------------- | ----------------- | --------------------------------------------------------------------------- |
| `field`             | `str`             | Name of the field (with index for list items, e.g. `"ports[0]"`)            |
| `expected`          | `str`             | Readable name of the expected type                                          |
| `value`             | `str`             | The string value that could not be converted                                |
| `reason`            | `str`             | Why the conversion failed                                                   |
| `config_path`       | `str`             | Full config path of the value (e.g. `"server.port"`)                        |
| `source_expression` | `str \| None`     | The unresolved interpolation the value came from, if any                    |
| `env_vars`          | `tuple[str, ...]` | Environment variables referenced by `source_expression`                     |

**Example:**

```python
try:
    app = rc.instantiate(path="app.yaml")
except rc.ValueCoercionError as e:
    print(e.config_path, e.env_vars)  # debug ('DEBUG',)
```
