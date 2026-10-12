# Advanced Usage & Troubleshooting

## Using Classes Directly

For more control, use the underlying classes:

```python
from rconfig import ConfigStore, ConfigValidator, ConfigInstantiator

store = ConfigStore()
store.register(name="model", target=ModelConfig)

validator = ConfigValidator(store)
instantiator = ConfigInstantiator(store, validator)

config = {"_target_": "model", "hidden_size": 256}
result = validator.validate(config)
if result.valid:
    model = instantiator.instantiate(config)
```

## Custom File Loaders

ReausoConfig includes built-in loaders for YAML, JSON, and TOML:

- `YamlConfigLoader` - `.yaml`, `.yml` files
- `JsonConfigLoader` - `.json` files
- `TomlConfigLoader` - `.toml` files (Python 3.11+)

To add support for additional file formats, create a custom loader and register it for specific extensions:

```python
from rconfig import ConfigFileLoader, register_loader
from pathlib import Path
from typing import Any
import configparser

class IniConfigLoader(ConfigFileLoader):
    def load(self, path: Path) -> dict[str, Any]:
        parser = configparser.ConfigParser()
        parser.read(path)
        # Convert to nested dict
        return {s: dict(parser[s]) for s in parser.sections()}

# Register for .ini extension
register_loader(IniConfigLoader(), ".ini")

# Now works with instantiate
model = rc.instantiate(path=Path("config.ini"))
```

## Thread Safety

ReausoConfig is thread-safe for concurrent access. The following operations can be safely called from multiple threads:

- `rc.register()` / `rc.unregister()` - Thread-safe class registration
- `rc.instantiate()` - Thread-safe config loading and instantiation
- `rc.validate()` - Thread-safe validation
- `rc.set_cache_size()` / `rc.clear_cache()` - Thread-safe cache management
- `register_loader()` / `unregister_loader()` - Thread-safe loader registration
- `register_exporter()` / `unregister_exporter()` - Thread-safe exporter registration

**Note:** `rc.known_targets()` returns a live view of registrations. Individual read operations are thread-safe, but iteration during concurrent mutation may raise RuntimeError.

## Error Handling

ReausoConfig provides a hierarchy of exceptions:

```
ConfigError (base)
├── ConfigFileError               # File loading issues
├── TargetNotFoundError           # Unknown _target_
├── ValidationError               # Validation failures
│   ├── MissingFieldError             # Required field missing
│   ├── TypeMismatchError             # Wrong type provided
│   │   └── ValueCoercionError            # String value cannot be converted to the field type
│   ├── AmbiguousTargetError          # Cannot infer type (abstract/multiple impls)
│   ├── TargetTypeMismatchError       # Explicit _target_ wrong type
│   ├── TypeInferenceError            # Inferred type validation failed
│   └── RequiredValueError            # _required_ value not provided
├── CompositionError              # Config composition issues
│   ├── CircularRefError              # Circular _ref_ detected
│   ├── RefResolutionError            # Cannot resolve _ref_ path
│   ├── AmbiguousRefError             # Multiple files match extension-less _ref_
│   ├── RefAtRootError                # _ref_ at root level
│   ├── RefInstanceConflictError      # Both _ref_ and _instance_ in same block
│   ├── CircularInstanceError         # Circular _instance_ detected
│   ├── InstanceResolutionError       # Cannot resolve _instance_ path
│   ├── InvalidInnerPathError         # Invalid inner_path for partial instantiation
│   └── MergeError                    # Deep merge failed
├── InterpolationError            # Interpolation issues
│   ├── InterpolationSyntaxError      # Invalid ${...} syntax
│   ├── InterpolationResolutionError  # Path/env not found
│   ├── CircularInterpolationError    # Circular ${...} reference
│   ├── EnvironmentVariableError      # Required env var not set
│   └── ResolverError                 # Custom resolver issues
│       ├── UnknownResolverError          # Resolver path not registered
│       └── ResolverExecutionError        # Resolver function raised exception
├── OverrideError                 # Override-related errors
│   ├── InvalidOverridePathError      # Override path doesn't exist
│   └── InvalidOverrideSyntaxError    # Override string malformed
└── InstantiationError            # Object creation failed
```

Example error handling:

```python
from rconfig import (
    ConfigFileError, ValidationError, InstantiationError,
    AmbiguousTargetError, TypeInferenceError,
    UnknownResolverError, ResolverExecutionError
)

try:
    model = rc.instantiate(path=Path("config.yaml"))
except AmbiguousTargetError as e:
    print(f"Cannot infer type: {e}")
    print(f"Available targets: {e.available_targets}")
except TypeInferenceError as e:
    print(f"Inferred type validation failed: {e}")
except UnknownResolverError as e:
    print(f"Unknown resolver: {e}")
except ResolverExecutionError as e:
    print(f"Resolver failed: {e}")
except ConfigFileError as e:
    print(f"Could not load file: {e}")
except ValidationError as e:
    print(f"Invalid config: {e}")
except InstantiationError as e:
    print(f"Could not create object: {e}")
```

## Troubleshooting

Common errors and how to fix them:

### `TargetNotFoundError: Target 'X' is not registered`

**Cause:** The `_target_` name in your config doesn't match any registered class.

**Fix:** Ensure you called `rc.register(name="X", target=MyClass)` before instantiation, and that the name matches exactly (case-sensitive).

```python
# Check what's registered
print(rc.known_targets().keys())
```

### `ConfigFileError: file not found`

**Cause:** The config file path doesn't exist or is relative to the wrong directory.

**Fix:** Verify the file exists and the path is correct relative to your working directory. Use absolute paths if unsure.

### `RefResolutionError` / `AmbiguousRefError`

**Cause:** A [`_ref_`](composition.md) path doesn't point to an existing file, or an extension-less ref matches multiple files (e.g., both `model.yaml` and `model.json` exist).

**Fix:** Check that the referenced file exists. If using extension-less refs, ensure only one file with that stem exists, or specify the extension explicitly.

### `CircularInterpolationError`

**Cause:** Two or more `${...}` expressions reference each other, creating a cycle.

**Fix:** Break the cycle by using a literal value for one of the expressions instead of a reference.

```yaml
# Wrong - circular
a: ${/b}
b: ${/a}

# Fix - break the cycle
a: ${/b}
b: 42
```

### `AmbiguousTargetError: Cannot infer type`

**Cause:** A nested config dict has no [`_target_`](core-concepts.md#the-_target_-key) and the field's type hint is abstract or has multiple registered implementations.

**Fix:** Add an explicit `_target_` to the nested config block to specify which implementation to use.

### `RequiredValueError`

**Cause:** Config contains `_required_` markers that weren't satisfied by overrides, CLI arguments, or environment variables.

**Fix:** Provide values via `overrides={"key": value}`, CLI arguments (`key=value`, when [CLI overrides are enabled](composition.md#cli-overrides)), or environment variable [interpolation](interpolation.md) (`${env:KEY}`).

### `RefAtRootError`

**Cause:** A config file has [`_ref_`](composition.md) at its root level. Every config file must define an object dictionary directly.

**Fix:** Move the `_ref_` inside a nested key, or inline the referenced content directly.

## Key Strengths

- **Minimal coupling**: Only your startup code imports rconfig
- **Simple API**: Just `register`, `validate`, `instantiate`
- **Lazy instantiation**: Defer expensive initialization until first access
- **Type validation**: Catches type mismatches before instantiation
- **Implicit target inference**: Omit `_target_` for concrete nested types
- **Config composition**: Load and merge configs from files with `_ref_`
- **Instance sharing**: Share objects across config with `_instance_`
- **Interpolation**: Reference values with `${...}`, env vars, and full expressions
- **Provenance tracking**: Debug where each config value originated
- **Lightweight**: Focused feature set, no bloat
- **Pure Python output**: Instantiated objects have no framework dependency
