# Submitting DualTran to the Dify Marketplace

Status: prepared; submission is the maintainer's action. Flow (plan 64 C4):

1. **Fork** [langgenius/dify-plugins](https://github.com/langgenius/dify-plugins)
   to `seigwen/dify-plugins`.
2. Package the plugin:
   ```bash
   bash scripts/verify.sh                 # tests + package assertions
   ./tools/dify plugin package . -o dualtran.difypkg
   ```
   (The dify CLI: download `dify-plugin-linux-amd64` from the
   [dify-plugin-daemon releases](https://github.com/langgenius/dify-plugin-daemon/releases)
   into `tools/dify`, or use `brew install dify`.)
3. Add **exactly one file** to the fork: `seigwen/dualtran/dualtran.difypkg`,
   and open ONE pull request to `langgenius/dify-plugins`. Their CI validates
   the package; human review follows (~1 week).
4. The generated `.github/workflows/plugin-publish.yml` in this repo automates
   steps 2–3 on GitHub releases — it needs the `PLUGIN_ACTION` secret (a PAT
   with repo scope) and the fork to exist.

## Before submitting

- [ ] `bash scripts/verify.sh` green (22 pytest cases + package assertions).
- [ ] manifest version bumped + README/parity table current.
- [ ] `dualtran.difypkg` in the fork contains NO tests/, NO tools/dify (the
      assertions in scripts/verify.sh enforce this).

## Real-instance testing (user action)

Full chain testing needs a reachable Dify instance (self-hosted via the
official docker compose). In Dify: Plugins → install the `.difypkg` →
authorize the DualTran provider (engine + optional key) → run any workflow
with the **DualTran Translate** tool. The plugin's own integration harness
(`dify_plugin.integration.run.PluginRunner` with `IntegrationConfig(dify_cli_path=…)`)
can drive this programmatically once an instance is paired; the unit suite
already covers every network path with MockTransport.

## Marketplace listing copy (draft)

- **Name:** DualTran
- **Description:** Translate text with Google (free, no key) or your own AI
  model / DeepL (BYOK). From the makers of the DualTran browser extension.
- **Category:** Tools → Utilities / translation
