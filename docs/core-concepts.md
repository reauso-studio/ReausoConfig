# Core Concepts

## The `_target_` Key

The `_target_` key maps a config block to a registered Python class.

**Root config file:** The root configuration file **must** have a `_target_` field:

```yaml
_target_: my_model  # Required at root level
learning_rate: 0.001
```

**Nested configs:** For nested configuration blocks, `_target_` is **optional** when the parent class has a type hint pointing to a concrete class (not abstract and without multiple registered subclasses). The nested class does not need to be registered; it is inferred from the type hint and registered automatically. Only the root target must be registered. See [Target Resolution](object-instantiation.md#target-resolution) for details on when `_target_` can be omitted.

## ConfigStore

ConfigStore is the central registry that implements **target mappings** - the association between string identifiers and Python classes. When you register a target:

```python
rc.register(name="my_model", target=MyModel)
rc.register(name="my_dataset", target=MyDataset)
```

The registered names (`"my_model"`, `"my_dataset"`) are exactly the values you use for `_target_` in your config files:

```yaml
_target_: my_model    # Maps to MyModel class
hidden_size: 256
```

This decoupling allows config files to reference classes by stable string identifiers, independent of Python module paths or class renaming.

**Viewing registered targets:**

```python
refs = rc.known_targets()
for name, ref in refs.items():
    print(f"{name}: {ref.target_class}")
```

## Reserved Keys

ReausoConfig reserves the following keys (prefixed and suffixed with `_`) for framework use during composition and instantiation. These keys are consumed by the framework and **cannot be used as field names** in your configuration classes.

| Key           | Purpose                                            |
| ------------- | -------------------------------------------------- |
| `_target_`    | Maps config block to a registered Python class     |
| `_ref_`       | References another config file for composition     |
| `_instance_`  | Shares an instantiated object across config paths  |
| `_lazy_`      | Marks a nested config for lazy instantiation       |
| `_required_`  | Marks a value as required (must be overridden)     |
| `_extend_`    | Appends items to a list during deep merge          |
| `_prepend_`   | Prepends items to a list during deep merge         |

These keys are stripped from the config before instantiation and are not passed to your class constructors. If you use a reserved key as a field name in your class, that field will never receive a value from config.

## Validation

Before instantiation, configs are validated for:

- Required fields (parameters without defaults)
- Type compatibility (string values such as environment variables are first [converted](type-coercion.md) to the declared type)
- Target existence in registry

## Resolution Pipeline

When you call `rc.instantiate()`, the following steps execute in order:

```
1. LOAD        Parse the config file (YAML, JSON, or TOML)
2. COMPOSE     Resolve all _ref_ references and deep merge
3. OVERRIDE    Apply programmatic overrides, then CLI overrides if enabled (CLI wins)
4. INTERPOLATE Resolve all ${...} expressions, then convert string values to
               the declared field types (see Type Coercion)
5. EXTRACT     If inner_path is specified, extract that section
6. VALIDATE    Check required values and type compatibility
7. INSTANTIATE Recursively create objects via registered constructors
```

Lifecycle hooks fire at specific points during this pipeline: [`CONFIG_LOADED` runs after step 2, `BEFORE_INSTANTIATE` and `AFTER_INSTANTIATE` run per-object during step 7, and `ON_ERROR` runs if any step raises an exception](multirun-and-hooks.md#lifecycle-hooks).
