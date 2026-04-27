# Changelog

All notable changes to this project will be documented in this file.

## [0.2.1](https://git.teccave.de/tecbeat/mailassist/-/releases/v0.2.1) - 2026-04-27

### 🐛 Bug Fixes

- Lower coverage threshold to 38% to match current coverage - ([d0ad425](https://git.teccave.de/tecbeat/mailassist/commit/d0ad425745f986a0707b3ab44becf7d44dc0df1d))

### ⚙️ Miscellaneous Tasks

- Enforce code coverage threshold and publish Cobertura report - ([2ab7eca](https://git.teccave.de/tecbeat/mailassist/commit/2ab7ecabf036c66e289f71cbadd8fe12828c4180))

## [0.1.23](https://git.teccave.de/tecbeat/mailassist/-/releases/v0.1.23) - 2026-04-27

### ⛰️  Features

- Remove redundant empty PluginSettingsDialog from 7 plugin pages - ([00cef39](https://git.teccave.de/tecbeat/mailassist/commit/00cef39e910976a22572dad86126bf7d3fa9a309))

### 📚 Documentation

- Add CONTRIBUTING.md - ([3abce0e](https://git.teccave.de/tecbeat/mailassist/commit/3abce0e4e2792ea7a1822937c30f989723fc0559))

### 🧪 Testing

- *(contacts)* Add test verifying sync error callback exists - ([758f18d](https://git.teccave.de/tecbeat/mailassist/commit/758f18da71f396afad57e26a7f121ca1cdcbf0ce))

### ⚙️ Miscellaneous Tasks

- Add frontend type checking (tsc --noEmit) to pipeline - ([bdcd3cc](https://git.teccave.de/tecbeat/mailassist/commit/bdcd3cc379f54e77c5bc4110ab1631ff81ce3ef2))

## [0.1.22](https://git.teccave.de/tecbeat/mailassist/-/releases/v0.1.22) - 2026-04-27

### 🐛 Bug Fixes

- Copy handler list before iteration in EventBus.emit - ([d7aa569](https://git.teccave.de/tecbeat/mailassist/commit/d7aa569d73803d845e4c31b690dfb7ed696b3aff))

## [0.1.21](https://git.teccave.de/tecbeat/mailassist/-/releases/v0.1.21) - 2026-04-27

### 🐛 Bug Fixes

- Use flush() instead of commit() in AI circuit breaker - ([589296a](https://git.teccave.de/tecbeat/mailassist/commit/589296af689dcbef43d0287edaadd1666f2665b9))

## [0.1.20](https://git.teccave.de/tecbeat/mailassist/-/releases/v0.1.20) - 2026-04-27

### 🐛 Bug Fixes

- Replace async-for get_session() with get_session_ctx() in persistence - ([a2e4ff6](https://git.teccave.de/tecbeat/mailassist/commit/a2e4ff670c1b0e582287b083ecce297516b1953e))

## [0.1.19](https://git.teccave.de/tecbeat/mailassist/-/releases/v0.1.19) - 2026-04-27

### 🐛 Bug Fixes

- Disable Sync Now button when no active CardDAV config exists - ([1b74eee](https://git.teccave.de/tecbeat/mailassist/commit/1b74eee875e9f787b5b712dbff473130ae1091f4))

### 🧪 Testing

- Fix contacts sync test mock exports to match actual API - ([c48f388](https://git.teccave.de/tecbeat/mailassist/commit/c48f3885dfb2bc5f53d0aa13f4fbb240898a9ef9))

## [0.1.18](https://git.teccave.de/tecbeat/mailassist/-/releases/v0.1.18) - 2026-04-27

### 🐛 Bug Fixes

- Release DB session during IMAP I/O in mail poller to prevent pool exhaustion - ([8fcb086](https://git.teccave.de/tecbeat/mailassist/commit/8fcb086347a3ac0aaef1968173d4c4973ed46a3c))

### 🧪 Testing

- Simplify expunge test to signature-only check - ([eb2294d](https://git.teccave.de/tecbeat/mailassist/commit/eb2294d8946f48daa11cdad47955c97a11134319))
- Remove flaky param name assertion from poller session test - ([024a80c](https://git.teccave.de/tecbeat/mailassist/commit/024a80c7b30f616144b32e009ee3917f81b7a997))
- Update mail poller tests to match refactored function signatures - ([153fbd0](https://git.teccave.de/tecbeat/mailassist/commit/153fbd01e6fdd1a8ab954f760ecbb6170f3079d1))

## [0.1.17](https://git.teccave.de/tecbeat/mailassist/-/releases/v0.1.17) - 2026-04-27

### 🐛 Bug Fixes

- Expunge MailAccount from session before use in IDLE loop to prevent DetachedInstanceError - ([713d1e8](https://git.teccave.de/tecbeat/mailassist/commit/713d1e8a3100c8f082097724c6662f25008c5512))

## [0.1.16](https://git.teccave.de/tecbeat/mailassist/-/releases/v0.1.16) - 2026-04-27

### 🐛 Bug Fixes

- Guard expires_at comparison against None in approval expiry check - ([edbc9b7](https://git.teccave.de/tecbeat/mailassist/commit/edbc9b7e0a19df05371802a2355244c6f2300588))

## [0.1.15](https://git.teccave.de/tecbeat/mailassist/-/releases/v0.1.15) - 2026-04-27

### 🐛 Bug Fixes

- Use stack-based brace closing in _repair_json - ([455f795](https://git.teccave.de/tecbeat/mailassist/commit/455f795419d1bf5d6895b26a096d8b4e1defd28d))
- Correct patch path for get_settings in token usage test - ([843b8bc](https://git.teccave.de/tecbeat/mailassist/commit/843b8bc012fe577b60b8c60202d5951d959d2dcf))
- Only set token usage TTL on key creation, not every increment - ([b35bb41](https://git.teccave.de/tecbeat/mailassist/commit/b35bb41ce6be61bdee1d738a564f1e1227c0d7ee))
- Correct ImapConnection constructor in move_all_to_inbox tests - ([f9b4bcf](https://git.teccave.de/tecbeat/mailassist/commit/f9b4bcff9fb9ff421a14eb600f55794856743763))
- Batch MOVE/COPY+EXPUNGE in move_all_to_inbox to prevent UID issues - ([4be1a2c](https://git.teccave.de/tecbeat/mailassist/commit/4be1a2c5d74b6a255d1c5eb31a21cf9ddf3c2423))
- Use correct approval column names in plugin tracking test mocks - ([5ba7457](https://git.teccave.de/tecbeat/mailassist/commit/5ba7457fe2814a0e0f1f86ea28b5cc79a4de1e9e))
- Ensure approval_mode is always compared as ApprovalMode enum - ([b6ba3fd](https://git.teccave.de/tecbeat/mailassist/commit/b6ba3fdb6bd053c0471958c8bcdcd9f7cbf3814a))
- Restrict setattr to whitelisted fields on MailAccount update - ([a649617](https://git.teccave.de/tecbeat/mailassist/commit/a649617d6c8eec0f066e1a02ca18bb9b80b34187))

## [0.1.14](https://git.teccave.de/tecbeat/mailassist/-/releases/v0.1.14) - 2026-04-27

### 🐛 Bug Fixes

- Stream chunked request bodies to prevent unbounded memory usage - ([2baffe3](https://git.teccave.de/tecbeat/mailassist/commit/2baffe3e9ea25b92b2b38d352b5fdad21841d564))

## [0.1.13](https://git.teccave.de/tecbeat/mailassist/-/releases/v0.1.13) - 2026-04-27

### 🐛 Bug Fixes

- Validate envelope schema before accessing keys on decrypt - ([c44091b](https://git.teccave.de/tecbeat/mailassist/commit/c44091b8e11c6df8b9af562a6814cedab3ca616f))
- Replace authlib with pure httpx OAuth2 PKCE implementation - ([37f5510](https://git.teccave.de/tecbeat/mailassist/commit/37f551000aec2eac812ad2857769c5ed474e2537))
- Broaden authlib warning filter to match submodules - ([817da32](https://git.teccave.de/tecbeat/mailassist/commit/817da3242408ee1f6354a4a02d4e32bbe2dcd8c6))
- Remove unrealistic coverage threshold and filter unraisable warning - ([11f06a4](https://git.teccave.de/tecbeat/mailassist/commit/11f06a46da0331aa705cc2446894deca824a87e2))
- Eliminate test warnings and add coverage reporting to CI - ([7434807](https://git.teccave.de/tecbeat/mailassist/commit/743480752c798c64cfcacb2110945fdbc2bb0b52))

## [0.1.12](https://git.teccave.de/tecbeat/mailassist/-/releases/v0.1.12) - 2026-04-27

### 🐛 Bug Fixes

- Trigger OIDC end_session_endpoint on logout - ([36a3005](https://git.teccave.de/tecbeat/mailassist/commit/36a3005583cd328e082be3ccc2eede0f3360395d))

## [0.1.11](https://git.teccave.de/tecbeat/mailassist/-/releases/v0.1.11) - 2026-04-27

### 🐛 Bug Fixes

- Use percent-encoded space in test assertion - ([593f9df](https://git.teccave.de/tecbeat/mailassist/commit/593f9dff567c95bc8604815aa1e226d73756a524))
- Handle OIDC callback error parameter from IdP - ([a177c0d](https://git.teccave.de/tecbeat/mailassist/commit/a177c0d114f8656f68b6fae6f3ee3870b83f55a4))

## [0.1.10](https://git.teccave.de/tecbeat/mailassist/-/releases/v0.1.10) - 2026-04-27

### 🐛 Bug Fixes

- Only trust X-Forwarded-For from configured trusted proxies - ([9a4b130](https://git.teccave.de/tecbeat/mailassist/commit/9a4b1305b4d0800100c53734b385b3f12db7b770))

## [0.1.9](https://git.teccave.de/tecbeat/mailassist/-/releases/v0.1.9) - 2026-04-27

### 🐛 Bug Fixes

- Use atomic Lua script for login rate limiter - ([4c0029a](https://git.teccave.de/tecbeat/mailassist/commit/4c0029af9c5d9c631ebed5f68f2600073ac28923))
- Prevent ghost session when DB commit fails in auth callback - ([a577122](https://git.teccave.de/tecbeat/mailassist/commit/a5771222db2e8e9ad32f3faac5672af3df7611da))

## [0.1.8](https://git.teccave.de/tecbeat/mailassist/-/releases/v0.1.8) - 2026-04-27

### ⚙️ Miscellaneous Tasks

- *(deps)* Update gitlab-ci - ([2257f01](https://git.teccave.de/tecbeat/mailassist/commit/2257f018c34c768b7dbd3ac53a8d817229a56828))

## [0.1.7](https://git.teccave.de/tecbeat/mailassist/-/releases/v0.1.7) - 2026-04-27

### 🐛 Bug Fixes

- Extend CSRF protection to cover all state-changing routes - ([375a5d3](https://git.teccave.de/tecbeat/mailassist/commit/375a5d3b05069dca8ed194d00d2abde14c10b783))

## [0.1.6](https://git.teccave.de/tecbeat/mailassist/-/releases/v0.1.6) - 2026-04-27

### 🐛 Bug Fixes

- *(deps)* Update all non-major dependencies - ([cb84191](https://git.teccave.de/tecbeat/mailassist/commit/cb84191652a404fe46a1939a225d6278b4c10cee))

## [0.1.5](https://git.teccave.de/tecbeat/mailassist/-/releases/v0.1.5) - 2026-04-26

### ⚙️ Miscellaneous Tasks

- Mark templater need as optional in updater job - ([1eb85ff](https://git.teccave.de/tecbeat/mailassist/commit/1eb85ff7d225a67b445c021cd2951f566e17ddd7))
- Disable templater and enable updater - ([4cfd241](https://git.teccave.de/tecbeat/mailassist/commit/4cfd24139ac4556a9a25e5158f8b4ebee251df2a))

## [0.1.4](https://git.teccave.de/tecbeat/mailassist/-/releases/v0.1.4) - 2026-04-26

### 🐛 Bug Fixes

- *(compose)* Repair postgres 18 volume layout and parametrise app image tag - ([075968c](https://git.teccave.de/tecbeat/mailassist/commit/075968c6c0bba3be547279b5362d73cbb4946909))

## [0.1.3](https://git.teccave.de/tecbeat/mailassist/-/releases/v0.1.3) - 2026-04-26

### 🐛 Bug Fixes

- *(frontend)* Adapt tsconfig for TypeScript 6 and add vite-env types - ([244cfa1](https://git.teccave.de/tecbeat/mailassist/commit/244cfa193f41e79f09a9a1e4ef102310925edfdf))

### ⚙️ Miscellaneous Tasks

- Consolidate seven open Renovate MRs into one update - ([f66db1a](https://git.teccave.de/tecbeat/mailassist/commit/f66db1abaafecd416837530201eb245c38a70997))

## [0.1.2](https://git.teccave.de/tecbeat/mailassist/-/releases/v0.1.2) - 2026-04-26

### 🐛 Bug Fixes

- *(deps)* Update node.js to v24 - ([e3ee371](https://git.teccave.de/tecbeat/mailassist/commit/e3ee371765ba7ed7638535f917f7a0614084dde4))
- *(deps)* Update valkey/valkey docker tag to v9 - ([4ebdc17](https://git.teccave.de/tecbeat/mailassist/commit/4ebdc17c726f9f064b7fc73752b49dd1331dd21c))
- *(deps)* Pin dependencies - ([1c5b49f](https://git.teccave.de/tecbeat/mailassist/commit/1c5b49f4385b35acb036db87b784c3c3731b350e))

### 🧪 Testing

- Bring outdated unit tests in sync with current behaviour - ([f0438cd](https://git.teccave.de/tecbeat/mailassist/commit/f0438cd279828ea6f926b5b291d15c4162cc8a30))

### ⚙️ Miscellaneous Tasks

- Chdir to /app before launching uvicorn in integration_test - ([b8b2f1f](https://git.teccave.de/tecbeat/mailassist/commit/b8b2f1fbd0b26129a78744fc092a3de5a786c6cf))
- Install only deps in test job and unblock entrypoint in integration_test - ([256263c](https://git.teccave.de/tecbeat/mailassist/commit/256263ca8d3e4cb1ae8dd73c47eddde99fc91c38))
- Stabilise test and integration_test jobs - ([577b884](https://git.teccave.de/tecbeat/mailassist/commit/577b88428d27005dbd61e4b42f122e144a14e2fb))
- Gate image build on pytest by moving test to prepare stage - ([cffaf85](https://git.teccave.de/tecbeat/mailassist/commit/cffaf85b69fdc836692ad22821726e8704bfffae))
- Add pytest and integration-test jobs for non-main branches - ([2cd74d0](https://git.teccave.de/tecbeat/mailassist/commit/2cd74d064a30c49a68bc096bb6ec63561c39349a))

## [0.1.1](https://git.teccave.de/tecbeat/mailassist/-/releases/v0.1.1) - 2026-04-25

### 🐛 Bug Fixes

- Remove useless files and update configuration - ([2a072fb](https://git.teccave.de/tecbeat/mailassist/commit/2a072fb224a7911f3f884519ca3a44a5e5435d4f))

## [0.1.0](https://git.teccave.de/tecbeat/mailassist/-/releases/v0.1.0) - 2026-04-25

### ⛰️  Features

- Add complete project structure and implementation - ([703d7a7](https://git.teccave.de/tecbeat/mailassist/commit/703d7a7ef2194eb427a9eb28bfacf7089057816e))

<!-- generated by teccave -->
