# Client configs

Each client gets exactly one YAML file in this folder, named `<client_id>.yaml`, with the shape shown in `kaiser-team.yaml`: `client_id`, `display_name`, a `territory` block (`planning_areas`, `zips`, `neighborhoods`), `owner_data_provider` (`sample` or `attom`), an `outreach` block with `mode`, and a `team_members` list. The file is loaded and validated by `pipelines/territory/config.py`; unknown or invalid fields fail validation. One codebase serves every client, and each client gets its own deployment pointed at its own config.
