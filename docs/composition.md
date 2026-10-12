# Config Composition

## Config Composition with `_ref_`

Load configurations from other files and merge them:

```yaml
# models/resnet.yaml
_target_: model
hidden_size: 256
dropout: 0.1

# trainer.yaml
_target_: trainer
model:
  _ref_: models/resnet  # Load from file (auto-detects format)
  dropout: 0.2          # Override: merged on top
epochs: 10
```

**Path resolution:**

| Syntax              | Example            | Description                       |
| ------------------- | ------------------ | --------------------------------- |
| Relative (implicit) | `models/resnet`  | Relative to current file          |
| Relative (explicit) | `./local`        | Explicit relative to current file |
| Parent directory    | `../shared/base` | Navigate up directories           |
| Absolute            | `/models/resnet` | From config root directory        |

**Extension-less resolution:** `_ref_` paths can omit the file extension. The format is detected automatically from whatever file exists with that stem:

```yaml
model:
  _ref_: models/vit  # Finds models/vit.yaml, models/vit.json, or models/vit.toml
```

This makes configs format-agnostic — you can switch a referenced file from YAML to JSON without updating any `_ref_` paths that point to it.

If multiple files share the same stem (e.g., `vit.yaml` and `vit.json` both exist), rconfig raises `AmbiguousRefError`. Either remove the duplicate or specify the extension explicitly:

```yaml
model:
  _ref_: models/vit.yaml  # Explicit — no ambiguity
```

If no file with the stem exists, `RefResolutionError` is raised.

### Root-Level `_ref_` Restriction

`_ref_` is **not allowed at the root level** of any config file. Every config file must define an object dictionary directly — it cannot be just a reference to another file:

```yaml
# WRONG - raises RefAtRootError
_ref_: ./base.yaml

# CORRECT - nest the reference inside a key
_target_: trainer
model:
  _ref_: ./base.yaml
```

If you want to reuse an entire file's content, either inline it directly or reference it from a parent config's nested key.

### Deep Merge Semantics

When a `_ref_` is merged with sibling keys, deep merge rules determine how values combine:

| Value Type | Behavior | Example |
|-----------|----------|---------|
| **Dicts** | Recursively merged (both sides preserved; override wins on conflict) | `{a: 1, b: 2}` + `{b: 3, c: 4}` → `{a: 1, b: 3, c: 4}` |
| **Lists** | Completely replaced (not appended) | `[1, 2, 3]` + `[4]` → `[4]` |
| **Scalars** | Replaced by override | `lr: 0.01` + `lr: 0.1` → `lr: 0.1` |

```yaml
# base.yaml
_target_: model
layers:
  hidden_size: 256
  dropout: 0.1
callbacks: [logger, checkpoint]
lr: 0.01

# trainer.yaml
_target_: trainer
model:
  _ref_: base.yaml
  layers:
    dropout: 0.2      # Dict merge: hidden_size preserved, dropout overridden
  callbacks: [early_stop]  # List replaced entirely (not appended)
  lr: 0.001               # Scalar replaced
```

Result after merge:
```yaml
model:
  _target_: model
  layers:
    hidden_size: 256   # Preserved from base
    dropout: 0.2       # Overridden
  callbacks: [early_stop]  # Replaced (not [logger, checkpoint, early_stop])
  lr: 0.001                # Replaced
```

#### List Operations: `_extend_` and `_prepend_`

To append or prepend items to a list instead of replacing it, use `_extend_` or `_prepend_`:

```yaml
# base.yaml
callbacks: [logger, checkpoint]

# trainer.yaml
model:
  _ref_: base.yaml
  callbacks:
    _extend_: [early_stop, profiler]   # Appends to list
    # Result: [logger, checkpoint, early_stop, profiler]
```

```yaml
# Or prepend:
model:
  _ref_: base.yaml
  callbacks:
    _prepend_: [setup]   # Prepends to list
    # Result: [setup, logger, checkpoint]
```

**Constraints:**

- Cannot use both `_extend_` and `_prepend_` in the same block
- Cannot combine list operations with other keys in the same block
- The base value must already be a list

## Instance Sharing with `_instance_`

Share object instances across your config:

```yaml
_target_: app
shared_cache:
  _target_: cache
  size: 100

service_a:
  _target_: service
  cache:
    _instance_: shared_cache  # Same object as shared_cache

service_b:
  _target_: service
  cache:
    _instance_: shared_cache  # Same object, shared with service_a
```

**Path resolution:**

| Syntax              | Example                  | Description               |
| ------------------- | ------------------------ | ------------------------- |
| Absolute            | `/shared.database`     | From composed config root |
| Relative (implicit) | `shared_cache`         | Relative to config root   |
| Relative (explicit) | `./shared`             | Explicit relative syntax  |
| Parent              | `../sibling.value`     | Parent-relative path      |
| Nested              | `data.sources.primary` | Dot notation for nesting  |
| List indexing       | `databases[0]`         | Access list element       |

**Special values:**

- `_instance_: null` - Passes `None` to constructor

## CLI Overrides

Override config values from the command line:

```bash
python main.py model.hidden_size=512 epochs=20
```

CLI overrides are **opt-in**. By default ReausoConfig never reads `sys.argv`, so loading config inside a web app, worker or test runner cannot be affected by the host program's arguments. Enable them once at the start of a script, or per call:

```python
rc.set_cli_overrides(True)  # Process-wide, e.g. at the top of train.py
trainer = rc.instantiate(path=Path("config.yaml"))

# Or only for one call
trainer = rc.instantiate(path=Path("config.yaml"), cli_overrides=True)
```

A per-call `cli_overrides=True`/`False` always takes precedence over `rc.set_cli_overrides()`.

Or programmatically:

```python
trainer = rc.instantiate(
    path=Path("config.yaml"),
    overrides={"model.hidden_size": 512, "epochs": 20},
)
```

### Override Syntax

| Syntax        | Example                | Description      |
| ------------- | ---------------------- | ---------------- |
| Dot notation  | `model.lr=0.01`      | Set nested value |
| List indexing | `layers[0].size=128` | Set list element |
| Add to list   | `+callbacks=logger`  | Append to list   |
| Remove key    | `~dropout`           | Delete key       |

### CLI `_ref_` Shorthand

When overriding a dict field from CLI, you can use shorthand syntax to reference another config file:

```bash
# Instead of:
python train.py model._ref_=models/vit.yaml

# You can write:
python train.py model=models/vit.yaml
```

**How it works:** If the target field is a dict in your config, the override is automatically converted to a `_ref_` assignment. This loads and merges the referenced config file.

**When shorthand applies:**

- Target field exists AND is a dict
- Value is not quoted

**Force literal string:** Use quotes to prevent `_ref_` conversion:

```bash
python train.py model="models/vit.yaml"  # Literal string, not a ref
```

CLI values are converted to the declared field types with the same rules as [environment values](type-coercion.md), except that a comma does not split a list: write `tags=[a, b]` for a list, because `tags=a,b` means a [sweep](multirun-and-hooks.md#cli-syntax) in multirun.

### Disabling CLI Overrides

If CLI overrides are enabled process-wide, you can still ignore `sys.argv` for a single call:

```python
model = rc.instantiate(path=Path("config.yaml"), cli_overrides=False)
```

### CLI Help

When CLI overrides are enabled (`rc.set_cli_overrides(True)` or `cli_overrides=True`), all CLI-enabled functions support `--help` or `-h`:

```bash
python main.py --help
```

This displays all configurable entries from your config file:

```
Configuration options for config.yaml
=====================================

model.lr              float       0.001      Learning rate
model.hidden_size     int         256        Hidden layer size
data.path             str         (required) Path to data

Override with: python script.py key=value
```

**Functions that support CLI help:**

- `rc.instantiate()`
- `rc.validate()`
- `rc.to_dict()`
- `rc.to_yaml()`
- `rc.to_json()`
- `rc.to_toml()`
- `rc.to_file()`
- `rc.to_files()`
- `rc.export()`

The help output never applies the other CLI overrides, so a malformed argument cannot prevent `--help` from showing. `--help`/`-h` is removed from `sys.argv` when it is handled.

**Custom help formatting:**

```python
from rconfig.help import GroupedHelpIntegration

rc.set_help_integration(GroupedHelpIntegration())
```

See [Help Integration Classes](api-reference.md#help-integration-classes) in the API Reference for custom integrations.

### Override Priority

When both programmatic and CLI overrides are provided, CLI wins:

```python
# CLI: python main.py model.lr=0.05
trainer = rc.instantiate(path=Path("config.yaml"), overrides={"model.lr": 0.01})
# Result: model.lr = 0.05 (CLI wins)
```
