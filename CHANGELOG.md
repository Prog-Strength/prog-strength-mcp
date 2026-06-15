# [0.18.0](https://github.com/Prog-Strength/prog-strength-mcp/compare/v0.17.0...v0.18.0) (2026-06-15)


### Features

* **steps:** MCP steps module (log_steps, goal get/set, get_steps) ([#8](https://github.com/Prog-Strength/prog-strength-mcp/issues/8)) ([363d9f9](https://github.com/Prog-Strength/prog-strength-mcp/commit/363d9f9ca446588211488d278d86696963306abd))

# [0.17.0](https://github.com/Prog-Strength/prog-strength-mcp/compare/v0.16.1...v0.17.0) (2026-06-15)


### Features

* **running:** forward max-effort estimates to the agent ([#7](https://github.com/Prog-Strength/prog-strength-mcp/issues/7)) ([0b57147](https://github.com/Prog-Strength/prog-strength-mcp/commit/0b57147ba91a8b220a8104ef493ed57a945b10f8))

## [0.16.1](https://github.com/Prog-Strength/prog-strength-mcp/compare/v0.16.0...v0.16.1) (2026-06-12)


### Bug Fixes

* **ci:** authenticate to AWS via the shared OIDC role ([#6](https://github.com/Prog-Strength/prog-strength-mcp/issues/6)) ([d809510](https://github.com/Prog-Strength/prog-strength-mcp/commit/d8095108e9e99b0d64f57d191caeb6f9ce573718))

# [0.16.0](https://github.com/Prog-Strength/prog-strength-mcp/compare/v0.15.0...v0.16.0) (2026-06-12)


### Features

* thread the API's request id through lookup_food_nutrition ([#5](https://github.com/Prog-Strength/prog-strength-mcp/issues/5)) ([1282f19](https://github.com/Prog-Strength/prog-strength-mcp/commit/1282f19ae8bd4a8b3761ba10e5c65d4fbc065c97))

# [0.15.0](https://github.com/Prog-Strength/prog-strength-mcp/compare/v0.14.0...v0.15.0) (2026-06-12)


### Features

* lookup_food_nutrition forwarder tool ([#4](https://github.com/Prog-Strength/prog-strength-mcp/issues/4)) ([98ccda8](https://github.com/Prog-Strength/prog-strength-mcp/commit/98ccda8d4b8017591da485849e9513cd4e71495f)), closes [prog-strength-docs#37](https://github.com/prog-strength-docs/issues/37)

# [0.14.0](https://github.com/Prog-Strength/prog-strength-mcp/compare/v0.13.0...v0.14.0) (2026-06-10)


### Features

* **running:** get_running_best_efforts MCP tool proxying GET /running/best-efforts ([#3](https://github.com/Prog-Strength/prog-strength-mcp/issues/3)) ([b959d86](https://github.com/Prog-Strength/prog-strength-mcp/commit/b959d865d4f297bfe9f49f1ae06e515810a0e2c7))

# [0.13.0](https://github.com/Prog-Strength/prog-strength-mcp/compare/v0.12.0...v0.13.0) (2026-06-06)


### Features

* **mcp:** log_custom_meal tool wrapping POST /nutrition-log/custom ([#2](https://github.com/Prog-Strength/prog-strength-mcp/issues/2)) ([f6a45ba](https://github.com/Prog-Strength/prog-strength-mcp/commit/f6a45badfa0773de8c15ee65e2fa298b7077eab5))

# [0.12.0](https://github.com/Prog-Strength/prog-strength-mcp/compare/v0.11.1...v0.12.0) (2026-06-03)


### Features

* **mcp:** timezone-aware nutrition tool contract ([#1](https://github.com/Prog-Strength/prog-strength-mcp/issues/1)) ([7918334](https://github.com/Prog-Strength/prog-strength-mcp/commit/7918334977aca0dbd7daa3c7db80dd8f9f6cd332))

## [0.11.1](https://github.com/Prog-Strength/prog-strength-mcp/compare/v0.11.0...v0.11.1) (2026-05-31)


### Bug Fixes

* **deploy:** write AWS_REGION to .env so awslogs driver finds the right region ([b0d3384](https://github.com/Prog-Strength/prog-strength-mcp/commit/b0d3384794eb16a68e3f2bd2a834a11675371e8f))

# [0.11.0](https://github.com/Prog-Strength/prog-strength-mcp/compare/v0.10.0...v0.11.0) (2026-05-31)


### Features

* **nutrition:** MCP tools for daily macro goals ([084f28d](https://github.com/Prog-Strength/prog-strength-mcp/commit/084f28d9b5f80a358b32fb206445234e0919b4d7))

# [0.10.0](https://github.com/Prog-Strength/prog-strength-mcp/compare/v0.9.0...v0.10.0) (2026-05-30)


### Features

* **nutrition:** log_consumption now requires meal ([972db18](https://github.com/Prog-Strength/prog-strength-mcp/commit/972db18c8f5f828f5c12d44fe8e36fdc7af181c9))

# [0.9.0](https://github.com/Prog-Strength/prog-strength-mcp/compare/v0.8.0...v0.9.0) (2026-05-30)


### Features

* **bodyweight:** MCP tools for logging readings + listing history (Phase 3) ([597dda8](https://github.com/Prog-Strength/prog-strength-mcp/commit/597dda850e1de24d06fbde65a5774af9f39e8e11))

# [0.8.0](https://github.com/Prog-Strength/prog-strength-mcp/compare/v0.7.0...v0.8.0) (2026-05-30)


### Features

* **nutrition:** recipe tools + recipe-aware log_consumption (Phase 2) ([8e1de20](https://github.com/Prog-Strength/prog-strength-mcp/commit/8e1de20537db7d55d2e66e5bb1c3a57f77d74a94))

# [0.7.0](https://github.com/Prog-Strength/prog-strength-mcp/compare/v0.6.1...v0.7.0) (2026-05-30)


### Features

* **nutrition:** pantry + nutrition log MCP tools (Phase 1) ([c0324f6](https://github.com/Prog-Strength/prog-strength-mcp/commit/c0324f66ef223e9ba0f2f53265bf1960a0579468))

## [0.6.1](https://github.com/Prog-Strength/prog-strength-mcp/compare/v0.6.0...v0.6.1) (2026-05-19)


### Bug Fixes

* **build:** build image on a native ARM runner ([f8808eb](https://github.com/Prog-Strength/prog-strength-mcp/commit/f8808eb881e72d69c242cfc49811db3f8093ac92))

# [0.6.0](https://github.com/Prog-Strength/prog-strength-mcp/compare/v0.5.1...v0.6.0) (2026-05-19)


### Features

* **build:** publish MCP image to ECR and pull from it on deploy ([68eb395](https://github.com/Prog-Strength/prog-strength-mcp/commit/68eb39597cc1621d4ad03e7139620665d8cef2b2))

## [0.5.1](https://github.com/Prog-Strength/prog-strength-mcp/compare/v0.5.0...v0.5.1) (2026-05-18)


### Bug Fixes

* **workouts:** unwrap paginated /workouts response envelope ([d40246b](https://github.com/Prog-Strength/prog-strength-mcp/commit/d40246b3515ee3ea8646e7561195624c186c640d))

# [0.5.0](https://github.com/Prog-Strength/prog-strength-mcp/compare/v0.4.0...v0.5.0) (2026-05-17)


### Features

* **auth:** Forward user JWT instead of minting per call ([c899caa](https://github.com/Prog-Strength/prog-strength-mcp/commit/c899caab601a0945ce705e5924fb654b6af34fb5))

# [0.4.0](https://github.com/Prog-Strength/prog-strength-mcp/compare/v0.3.0...v0.4.0) (2026-05-16)


### Features

* **workouts:** Add tools to allow agent to record user workouts ([5ee9693](https://github.com/Prog-Strength/prog-strength-mcp/commit/5ee9693d802d60d1869394c877b5ba17e4abe17a))

# [0.3.0](https://github.com/Prog-Strength/prog-strength-mcp/compare/v0.2.0...v0.3.0) (2026-05-15)


### Features

* **cicd:** Add a manual deploy workflow ([c1d7748](https://github.com/Prog-Strength/prog-strength-mcp/commit/c1d77480b4cacadca2e3a20c9c23b690cea8618b))

# [0.2.0](https://github.com/Prog-Strength/prog-strength-mcp/compare/v0.1.0...v0.2.0) (2026-05-15)


### Features

* **examples:** Add an example script to test chat with agent and MCP server ([6c3f0cf](https://github.com/Prog-Strength/prog-strength-mcp/commit/6c3f0cfb2cc05f03ee25c950b4d97afc04fcc62b))
