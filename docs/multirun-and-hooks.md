# Multirun, Hooks & Caching

## Multirun Support

Generate and instantiate multiple config combinations from sweep parameters and explicit experiments. Enables hyperparameter sweeps and ablation studies without external orchestration.

```python
import rconfig as rc
from pathlib import Path

for result in rc.instantiate_multirun(
    path=Path("config.yaml"),
    sweep={
        "model": ["models/resnet", "models/vit"],  # Extension-less refs
        "optimizer.lr": [0.01, 0.001],
    },
    overrides={"epochs": 100},
):
    # result.config: immutable dict (MappingProxyType)
    # result.instance: instantiated object
    # result.overrides: the specific overrides for this run

    # Save config for reproducibility
    rc.to_file(source=result, output_path=Path(f"runs/{run_id}/config.yaml"))

    # Run experiment
    train(result.instance)
```

### CLI Syntax

Sweep parameters and experiments can be specified via command line once CLI overrides are enabled (`rc.set_cli_overrides(True)` at the start of the script, or `cli_overrides=True` on `rc.instantiate_multirun()`); by default `sys.argv` is ignored:

```bash
# Comma-separated sweep values (cartesian product)
python train.py model=models/resnet,models/vit optimizer.lr=0.01,0.001

# Bracket syntax (clearer, handles values with commas)
python train.py "model=[models/resnet, models/vit]" "optimizer.lr=[0.01, 0.001]"

# Explicit experiments with -e/--experiment
python train.py -e model=models/resnet,lr=0.01 -e model=models/vit,lr=0.001

# Combine experiments with sweep
python train.py -e model=models/resnet -e model=models/vit optimizer.lr=0.01,0.001

# Generates 4 runs:
# - resnet + lr=0.01
# - resnet + lr=0.001
# - vit + lr=0.01
# - vit + lr=0.001
```

### Experiments + Sweep Combination

Define explicit experiment configurations and optionally sweep additional parameters:

```python
for result in rc.instantiate_multirun(
    path=Path("config.yaml"),
    experiments=[
        {"model": "models/resnet", "optimizer.lr": 0.01},
        {"model": "models/vit", "optimizer.lr": 0.001},
        {"model": "models/mlp", "optimizer.lr": 0.1, "epochs": 50},
    ],
    sweep={
        "data.augmentation": ["flip", "rotate", "crop"],
    },
    overrides={"epochs": 100},  # Default (can be overridden by experiment)
):
    # 3 experiments x 3 augmentations = 9 runs
    train(result.instance)
```

**Behavior:**

- If only `sweep` -> cartesian product of all sweep values
- If only `experiments` -> run each experiment as defined
- If both -> each experiment is expanded with sweep cartesian product
- `overrides` applied to all runs (experiments can override these)

**Override Priority:** CLI > experiment/sweep > constant overrides

### List-Type Parameter Sweeps

When sweeping a parameter that expects a list type, wrap each value in a list:

```python
# Parameter "callbacks" expects List[str]

# WRONG - looks like sweep over 3 string values
sweep={"callbacks": ["logger", "checkpoint", "early_stop"]}

# CORRECT - sweep over 2 list values
sweep={"callbacks": [
    ["logger", "checkpoint"],           # Run 1
    ["logger", "early_stop"],           # Run 2
]}
```

### Lazy Instantiation

Combine with lazy mode for memory-efficient sweeps:

```python
for result in rc.instantiate_multirun(
    path=Path("config.yaml"),
    sweep={"model": ["models/small.yaml", "models/large.yaml"]},
    lazy=True,  # Delay __init__ until first access
):
    if should_skip(result.config):
        continue  # Model not instantiated yet
    train(result.instance)  # Triggers instantiation
```

### Saving Multirun Configs

Use `to_file` directly with `MultirunResult`:

```python
for i, result in enumerate(rc.instantiate_multirun(...)):
    # Export config for reproducibility
    rc.to_file(source=result, output_path=Path(f"runs/run_{i}/config.yaml"))
    rc.to_file(source=result, output_path=Path(f"runs/run_{i}/config.json"))
```

### Error Handling

Errors are raised when accessing the `instance` property. Use try/except for graceful handling:

```python
# Pattern 1: Fail fast (let it raise)
for result in rc.instantiate_multirun(...):
    train(result.instance)  # Raises if this run failed

# Pattern 2: Handle errors individually with try/except
for result in rc.instantiate_multirun(...):
    try:
        train(result.instance)
    except (ValidationError, InstantiationError) as e:
        log_failure(result.overrides, e)
        continue
```

### Partial Instantiation with inner_path

Focus multirun sweeps on a specific section of your config using `inner_path`:

```python
# trainer.yaml contains: model, optimizer, data sections
# Only sweep over the model configuration
for result in rc.instantiate_multirun(
    path=Path("trainer.yaml"),
    inner_path="model",
    sweep={"lr": [0.01, 0.001]},
):
    model = result.instance  # Only the model section
    train_with_model(model)
```

This is useful when:

- You want to sweep hyperparameters for one component
- Testing different model configurations independently
- The full config is expensive to instantiate

Nested paths are supported:

```python
for result in rc.instantiate_multirun(
    path=Path("trainer.yaml"),
    inner_path="model.encoder",
    sweep={"hidden_dim": [256, 512]},
):
    encoder = result.instance
```

### Iterator Features

The returned `MultirunIterator` supports length, slicing, and reversal:

```python
results = rc.instantiate_multirun(...)

# Progress tracking with tqdm (auto-detects __len__)
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

## Lifecycle Hooks

Register callbacks at various stages of the configuration lifecycle. Useful for validation, logging, metrics, secrets injection, and experiment tracking.

### Hook Phases

| Phase | When Invoked | Typical Use Cases |
|-------|--------------|-------------------|
| `CONFIG_LOADED` | After config composition, before instantiation | Validation, logging, secrets injection |
| `BEFORE_INSTANTIATE` | Before each object's constructor | Metrics, transformation |
| `AFTER_INSTANTIATE` | After each object's constructor | Registration, tracking |
| `ON_ERROR` | When instantiation fails | Error logging, cleanup |

### Decorator Registration

```python
import rconfig as rc
from rconfig.hooks import HookContext

@rc.on_config_loaded
def validate_paths(ctx: HookContext) -> None:
    """Validate that data paths exist after config is loaded."""
    if ctx.config and "data" in ctx.config:
        path = Path(ctx.config["data"]["path"])
        if not path.exists():
            raise ValueError(f"Data path not found: {path}")

@rc.on_config_loaded(priority=10)
def early_validation(ctx: HookContext) -> None:
    """Run early (lower priority values run first)."""
    ...

@rc.on_config_loaded(pattern="**/model/*.yaml")
def model_only_hook(ctx: HookContext) -> None:
    """Only runs for config files matching the glob pattern."""
    ...

@rc.on_before_instantiate
def log_instantiation(ctx: HookContext) -> None:
    """Log each object instantiation."""
    print(f"Creating {ctx.target_name} at {ctx.inner_path}")

@rc.on_after_instantiate
def register_metrics(ctx: HookContext) -> None:
    """Register instantiated objects with a metrics system."""
    metrics.register(ctx.target_name, ctx.instance)

@rc.on_error
def log_failures(ctx: HookContext) -> None:
    """Log instantiation failures."""
    logger.error(f"Failed: {ctx.error}")
```

### Config Modification

`CONFIG_LOADED` hooks can modify the config by returning a new dict. This enables secrets injection, value transformation, and dynamic configuration:

```python
import os
from rconfig.hooks import HookContext

@rc.on_config_loaded
def inject_secrets(ctx: HookContext) -> dict | None:
    """Inject secrets from environment variables."""
    config = dict(ctx.config)  # Make mutable copy

    # Replace placeholder values with environment secrets
    if config.get("api_key") == "_required_":
        config["api_key"] = os.getenv("API_KEY")

    if config.get("db_password") == "_required_":
        config["db_password"] = os.getenv("DB_PASSWORD")

    return config  # Return modified config

@rc.on_config_loaded(priority=20)
def compute_derived_values(ctx: HookContext) -> dict | None:
    """Compute values based on other config settings."""
    config = dict(ctx.config)

    # Derive batch_size from available GPU memory
    if "auto_batch_size" in config and config["auto_batch_size"]:
        config["batch_size"] = calculate_optimal_batch_size()

    return config
```

Multiple hooks can chain modifications - each hook receives the config as modified by previous hooks (in priority order).

### Class-Based Callbacks

For callbacks that need to maintain state across multiple hooks:

```python
class ExperimentTracker(rc.Callback):
    """Track experiment lifecycle for MLflow/W&B integration."""

    def __init__(self, tracking_uri: str):
        self.tracking_uri = tracking_uri
        self.run_id = None

    def on_config_loaded(self, ctx: HookContext) -> None:
        self.run_id = start_run(self.tracking_uri)
        log_config(self.run_id, dict(ctx.config))

    def on_after_instantiate(self, ctx: HookContext) -> None:
        log_component(self.run_id, ctx.target_name)

    def on_error(self, ctx: HookContext) -> None:
        mark_failed(self.run_id, str(ctx.error))

# Register the callback
tracker = ExperimentTracker("http://mlflow.internal")
rc.register_callback(tracker)

# Later, unregister if needed
rc.unregister_callback(tracker)
```

### Explicit Registration

```python
from rconfig.hooks import HookPhase

# Register with explicit phase
rc.register_hook(HookPhase.CONFIG_LOADED, my_hook, name="my_hook")

# Unregister by name
rc.unregister_hook("my_hook")

# View all registered hooks
for phase, hooks in rc.known_hooks().items():
    for hook in hooks:
        print(f"{phase.name}: {hook.name}")
```

### HookContext Reference

The `HookContext` object passed to hooks contains:

| Field | Type | Available In | Description |
|-------|------|--------------|-------------|
| `phase` | `HookPhase` | All | Current lifecycle phase |
| `config_path` | `str` | All | Path to the config file |
| `config` | `MappingProxyType` | All | Read-only config dict |
| `inner_path` | `str \| None` | BEFORE/AFTER_INSTANTIATE | Path within config |
| `target_name` | `str \| None` | BEFORE/AFTER_INSTANTIATE | The _target_ name |
| `instance` | `Any \| None` | AFTER_INSTANTIATE | The created object |
| `error` | `Exception \| None` | ON_ERROR | The exception |

## Caching

ReausoConfig caches parsed config files to avoid redundant I/O and parsing. Caching is enabled by default with unlimited size.

### What's Cached

Parsed file contents (the dict result of YAML/JSON/TOML parsing) are cached in an LRU cache keyed by file path. Subsequent loads of the same file skip parsing entirely.

### When Caching Helps

- **Multiple instantiations** from the same config files (e.g., multirun sweeps)
- **Partial instantiation** with `inner_path` accessing the same base config repeatedly
- **Long-running applications** that re-read config files

### When to Clear the Cache

- After modifying config files during runtime (the cache doesn't watch for file changes)
- In test suites between tests to ensure isolation

```python
import rconfig as rc

# Limit cache to 100 files
rc.set_cache_size(size=100)

# Unlimited cache (default)
rc.set_cache_size(size=0)

# Clear all cached files
rc.clear_cache()
```

**Test fixture example:**

```python
def setup_function():
    rc.clear_cache()  # Ensure fresh config for each test
```
