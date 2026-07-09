# Publishing propelsdlc-copilot-stub

**Package**: `propelsdlc-copilot-stub`  
**CLI Command**: `propelsdlc-copilot-init`  
**Registry**: npm (public - no auth required for users)

---

## Quick Reference

| What | Command | Description |
|------|---------|-------------|
| Preview | `npm run test` | Dry-run (no files created) |
| Create local package | `npm pack` | Creates `.tgz` file locally for testing |
| Update version | `npm version patch` | Bump version (or `minor`/`major`) |
| **Publish to npm** | `npm publish --access public` | **Uploads to public npm registry** |
| Clean | `npm run clean` | Remove copied source files |

---

## Publishing Steps

### 1. One-Time Setup

```bash
# Create account at https://www.npmjs.com/signup

npm login
npm whoami  # Verify
```

**Enable Two-Factor Authentication (Required for Publishing):**

1. Go to https://www.npmjs.com/settings/YOUR_USERNAME/twofa/enable
2. Choose "Authorization and Publishing" (recommended) or "Authorization Only"
3. Scan QR code with authenticator app (Google Authenticator, Authy, etc.)
4. Enter verification code to confirm

**Alternative: Use Granular Access Token**

If you prefer automation without 2FA prompts:

1. Go to https://www.npmjs.com/settings/tokens
2. Click "Generate New Token" → "Granular Access Token"
3. Configure:
   - **Packages and scopes**: Select packages → "Read and write"
   - **Organizations**: None (for unscoped packages)
   - Enable "Bypass 2FA requirement"
4. Copy token and add to `~/.npmrc`:
   ```
   //registry.npmjs.org/:_authToken=YOUR_TOKEN_HERE
   ```

### 2. Publish New Version

```bash
cd .npm-package

# Update version
npm version patch   # 1.0.0 → 1.0.1
# or: npm version minor   # 1.0.0 → 1.1.0
# or: npm version major   # 1.0.0 → 2.0.0

# Test locally (creates .tgz file, does NOT publish)
npm pack
npm install -g propelsdlc-copilot-stub-*.tgz  # Installs CLI tool

# Navigate to test directory and RUN the command
cd /path/to/test
propelsdlc-copilot-init  # This copies the files

# PUBLISH to public npm registry (makes it available to everyone)
npm publish --access public

# Verify it's published (view online)
npm view propelsdlc-copilot-stub

# Clean up copied source files
npm run clean
```

### 3. Tag in Git

```bash
git add package.json
git commit -m "Release v1.0.x"
git tag v1.0.x
git push origin main --tags
```

---

## Key Difference: pack vs publish

**`npm pack`** → Creates local `.tgz` file for testing (nothing is uploaded)
- Use for: Testing package locally before publishing
- Creates: `propelsdlc-copilot-stub-1.0.0.tgz`
- Where: Local filesystem only

**`npm publish`** → Uploads to public npm registry (available to everyone)
- Use for: Making package publicly available
- Result: Package at https://www.npmjs.com/package/propelsdlc-copilot-stub
- Where: Public npm registry (anyone can `npm install`)

---

## How It Works

**Source Files Location**:
- `.github/`, `.vscode/`, `.propel/`, `.env.example` → in parent directory (tracked by git)

**Build Process**:
1. `prepare.js` copies source files from parent → `.npm-package/`
2. `.gitignore` ignores copied files (not tracked)
3. `npm publish` packages everything (397 files)
4. `npm run clean` removes copied files

**Result**: Source tracked once, included in package.

---

## User Installation

```bash
# Install globally
npm install -g propelsdlc-copilot-stub

# Navigate to your project root
cd /path/to/your/project

# Run installer (copies files to current directory)
propelsdlc-copilot-init

# Or use npx (no global install needed):
npx propelsdlc-copilot-stub
```

**What gets installed:**
```
your-project/                    (current directory where command is run)
├── .github/                    ← Copied here
├── .vscode/                    ← Copied here (includes mcp.json)
├── .propel/                    ← Copied here
└── .env.example                ← Copied here
```

The files are copied to **wherever you run the command** (current working directory).

**Important Notes**:
- Existing files are **SKIPPED** (not overwritten) - your customizations are preserved
- To update files, manually delete them first, then run `propelsdlc-copilot-init` again
- `npm uninstall -g propelsdlc-copilot-stub` only removes the CLI tool, NOT the copied files
- Configure `.vscode/mcp.json` with your MCP server settings and API keys

---

## Updating the Package (Future Releases)

### Scenario: You want to release version 1.0.1

```bash
# 1. Make changes to source files in parent directory
cd /path/to/PropelIQ-Stub-Copilot
# Edit .github/, .vscode/, .propel/, .env.example, mcp_config-example.json as needed

# 2. Go to .npm-package
cd .npm-package

# 3. Bump version
npm version patch   # 1.0.0 → 1.0.1

# 4. Test locally
npm pack
npm install -g propelsdlc-copilot-stub-2.0.1.tgz  # Installs CLI
cd /path/to/test
propelsdlc-copilot-init  # Runs CLI to copy files

# 5. Publish updated package
npm publish --access public

# 6. Verify
npm view propelsdlc-copilot-stub

# 7. Tag in git
cd ..
git add .npm-package/package.json
git commit -m "Release v1.0.1"
git tag v1.0.1
git push origin main --tags

# 8. Clean up
cd .npm-package
npm run clean
```

**How users get updates:**
```bash
# Users update the CLI tool
npm install -g propelsdlc-copilot-stub@latest

# Then manually delete old files and reinstall
rm -rf .github .vscode .propel .env.example
propelsdlc-copilot-init
```

---

## Useful Commands

```bash
npm whoami                           # Check login
npm pack --dry-run                  # Preview package
npm view propelsdlc-copilot-stub    # View published package
npm uninstall -g propelsdlc-copilot-stub  # Remove CLI tool (files remain in project)
npm unpublish propelsdlc-copilot-stub@2.0.0 --force  # Unpublish (within 72h)
```

