# propelsdlc-copilot-stub

GitHub Copilot configuration stub for PropelSDLC projects by KANINI Software Solutions. This package provides a complete setup for AI-assisted development with GitHub Copilot, including prompts, skills, instructions, and project configuration.

**PROPRIETARY SOFTWARE** - This software is the property of KANINI Software Solutions. See LICENSE file for terms and conditions.

## Installation

### Prerequisites

- Node.js >= 14.0.0
- npm (comes with Node.js)

### Install Package

```bash
npm install -g propelsdlc-copilot-stub
```

Or as a dev dependency in your project:

```bash
npm install --save-dev propelsdlc-copilot-stub
```

## Usage

Navigate to your project root directory and run:

```bash
npx propelsdlc-copilot-stub
```

Or if installed globally:

```bash
propelsdlc-copilot-init
```

The installer will copy configuration files to your current directory (where you run the command).

This will install the following to your project root:

- `.github/` - GitHub Copilot prompts, instructions, skills, and agents
- `.propel/` - PropelSDLC templates, rules, prompts, and orchestrators
- `.vscode/` - VS Code tasks and MCP configuration (mcp.json)
- `.env.example` - Environment variable template

**Note:** Existing files and folders will be skipped to preserve your customizations.

## What Gets Installed

### `.github/` Structure
- **prompts/** - Reusable AI prompts for various development tasks
- **skills/** - Domain-specific knowledge and coding standards
- **instructions/** - Development guidelines and best practices
- **agents/** - Custom GitHub Copilot agents
- **hooks/** - Copilot hooks configuration
- **copilot-instructions.md** - Main Copilot configuration

### `.propel/` Structure
- **prompts/** - Workflow prompts for change management and analysis
- **templates/** - Document templates for specs, plans, and artifacts
- **rules/** - Custom validation and enforcement rules
- **orchestrators/** - Workflow orchestration definitions
- **learnings/** - Captured patterns and findings
- **hooks/** - PropelSDLC hooks
- **instructions.md** - Core workflow instructions
- **id-scheme-registry.md** - ID scheme registry for artifacts
- **project-config.json** - Project configuration
- **requirements.txt** - Python dependencies for skills

### `.vscode/` Structure
- **mcp.json** - Model Context Protocol server configuration
- **tasks.json** - VS Code task definitions

## Post-Installation Steps

1. **Configure Environment Variables**
   - Rename `.env.example` to `.env`
   - Add your Context7 API key: `CONTEXT7_API_KEY=your-key-here`
   - **IMPORTANT**: Add `.env` to your `.gitignore` to prevent exposing sensitive keys:
     ```bash
     echo .env >> .gitignore
     ```
   
   **Note**: The Context7 API key is read from the `.env` file, not directly from `.vscode/mcp.json`
   
   Get your Context7 API key at: https://context7.ai

2. **Configure MCP Servers**
   
   Model Context Protocol (MCP) servers extend AI assistant capabilities:
   
   - Open `.vscode/mcp.json`
   - Review enabled servers:
     - `propel-iq` - PropelSDLC template and workflow management
     - `context7` - Semantic code search
     - `azure-mcp` - Azure resource management
     - `sequential-thinking` - Step-by-step reasoning
   - Enable/disable servers as needed by adding/removing entries
   - Configure server-specific settings (API keys, endpoints, etc.)
   - Restart VS Code after configuration changes
   
   **Common MCP Server Configurations:**
   
   ```json
   {
     "mcpServers": {
       "propel-iq": {
         "command": "npx",
         "args": ["-y", "@propelsdlc/mcp-server"]
       },
       "context7": {
         "command": "npx",
         "args": ["-y", "@context7/mcp-server"],
         "env": {
           "CONTEXT7_API_KEY": "your-key"
         }
       },
       "azure-mcp": {
         "command": "npx",
         "args": ["-y", "@azure/mcp-server"],
         "env": {
           "AZURE_SUBSCRIPTION_ID": "your-subscription-id"
         }
       }
     }
   }
   ```

3. **Customize Copilot Instructions**
   - Edit `.github/copilot-instructions.md` for your project
   - Review and modify `.github/instructions/*.instructions.md` as needed

4. **Configure PropelSDLC**
   - Update `.propel/project-config.json` with your project details
   - Review `.propel/instructions.md` for workflow guidance

5. **Install Python Dependencies (if using skills)**
   ```bash
   pip install -r .propel/requirements.txt
   ```

## Features

### AI-Assisted Development
- 40+ pre-configured prompts for common development tasks
- Specialized agents for specs, testing, and architecture
- Comprehensive coding standards and guidelines

### Change Management
- Structured change request workflows
- Impact analysis automation
- Traceability enforcement

### Quality Assurance
- Test plan generation
- Code review automation
- Edge case analysis

### Documentation
- Automatic spec generation
- UML and PlantUML support
- Figma integration for design specs

## Updating Configuration

The installer skips existing files to preserve your customizations. To update specific components:

### Option 1: Selective Update

1. **Backup your customizations**
   ```bash
   cp -r .github .github.backup
   cp -r .propel .propel.backup
   ```

2. **Remove what you want to update**
   ```bash
   # Example: Update only .github folder
   rm -rf .github
   ```

3. **Re-run installer from your project root**
   ```bash
   propelsdlc-copilot-init
   ```

4. **Merge customizations** from your backup if needed

### Option 2: Fresh Install

Remove all installed components and reinstall:
```bash
rm -rf .github .propel .vscode .env.example
propelsdlc-copilot-init
```

## Troubleshooting

### Files Already Exist
The installer automatically skips existing files and folders to preserve your customizations. If you want to reinstall specific items, remove or rename them first.

### Wrong Installation Directory
Always run `propelsdlc-copilot-init` from your project root directory. The installer copies files to the current working directory (where you execute the command).

### Permission Errors
Ensure you have write permissions in the target directory.

### Missing Dependencies
Some features require Python packages. Install them with:
```bash
pip install -r .propel/requirements.txt
```

### Environment Variables & Security
**Always add `.env` to `.gitignore`** to prevent exposing API keys:
```bash
echo .env >> .gitignore
```
Rename `.env.example` to `.env` and add your API keys. The Context7 API key is read from the `.env` file, not directly from `.vscode/mcp.json`.

Get your Context7 API key at: https://context7.ai

## Customization

All installed files are meant to be customized for your project. The installer creates a baseline configuration that you should adapt to your specific needs.

Key files to customize:
- `.github/copilot-instructions.md` - Main Copilot behavior
- `.github/instructions/*.instructions.md` - Coding standards for your stack
- `.propel/project-config.json` - Project-specific settings
- `.propel/instructions.md` - Workflow preferences

## Support

For licensing, support, or questions:
- Email: support@kanini.com
- Website: https://www.kanini.com/propelsdlc
- Documentation: Review installed files in `.github/` and `.propel/` folders

## License

Proprietary - Copyright (c) 2026 KANINI Software Solutions. All rights reserved.

This software is the property of KANINI Software Solutions and is protected by copyright law. Unauthorized copying, distribution, modification, or use of this software is strictly prohibited without prior written permission from KANINI Software Solutions.

See LICENSE file for complete terms and conditions.
