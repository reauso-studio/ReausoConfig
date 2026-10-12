# Serialization & Export

Export resolved configs to various formats without instantiation:

```python
import rconfig as rc
from pathlib import Path

# Export to Python dict (fully resolved)
config_dict = rc.to_dict(path=Path("config.yaml"))
print(config_dict["model"]["hidden_size"])  # 256

# Export to YAML string
yaml_str = rc.to_yaml(path=Path("config.yaml"))

# Export to JSON string
json_str = rc.to_json(path=Path("config.yaml"))

# Export to TOML string
toml_str = rc.to_toml(path=Path("config.yaml"))

# With overrides
config = rc.to_dict(
    path=Path("config.yaml"),
    overrides={"model.lr": 0.01}
)

# Remove internal markers (_target_, _ref_, _instance_, _lazy_)
clean_dict = rc.to_dict(path=Path("config.yaml"), exclude_markers=True)
```

## File Export

Export to files with automatic format detection based on output file extension:

```python
# Single file export - format auto-detected from extension
rc.to_file(source=Path("trainer.yaml"), output_path=Path("output.json"))   # YAML -> JSON
rc.to_file(source=Path("trainer.yaml"), output_path=Path("output.toml"))   # YAML -> TOML
rc.to_file(source=Path("trainer.yaml"), output_path=Path("output.yaml"))   # YAML -> YAML

# Export from dict (useful for post-processing)
config = {"model": {"lr": 0.01}, "epochs": 10}
rc.to_file(source=config, output_path=Path("output.yaml"))

# Post-processing workflow
config = rc.to_dict(path=Path("config.yaml"))
config["extra_key"] = "added_value"
rc.to_file(source=config, output_path=Path("output.json"))

# Multi-file export preserving _ref_ structure
rc.to_files(source=Path("trainer.yaml"), config_root_file=Path("output/trainer.json"))
# Creates:
#   output/trainer.json (root file in JSON format)
#   output/models/resnet.yaml (preserves original YAML format)
#   output/settings.toml (preserves original TOML format)
```

## Cross-Format Export

Load configs from any format and export to another:

```python
# Load YAML, export as JSON string
json_str = rc.to_json(path=Path("config.yaml"))

# Load TOML, export as YAML string
yaml_str = rc.to_yaml(path=Path("config.toml"))

# Load JSON, export to TOML file
rc.to_file(source=Path("config.json"), output_path=Path("output.toml"))
```

## Custom Exporters

Register custom exporters for additional formats:

```python
from rconfig import Exporter, register_exporter

class XmlExporter(Exporter):
    def export(self, config: dict) -> str:
        # Custom XML serialization logic
        return dict_to_xml(config)

# Register for .xml extension
register_exporter(XmlExporter(), ".xml")

# Now works with to_file
rc.to_file(source=Path("config.yaml"), output_path=Path("output.xml"))
```

For more control, use the `export()` function with a custom exporter instance:

```python
result = rc.export(path=Path("config.yaml"), exporter=MyCustomExporter())
```
