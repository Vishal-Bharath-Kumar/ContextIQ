#!/usr/bin/env node

/**
 * propelsdlc-copilot-stub Installer
 * Copyright (c) 2026 KANINI Software Solutions. All rights reserved.
 * Proprietary and confidential.
 */

const fs = require('fs');
const path = require('path');

// Source files are in the package root (one level up from bin/)
const SOURCE_DIR = path.join(__dirname, '..');
const TARGET_DIR = process.cwd();

const ITEMS_TO_COPY = [
  { src: '.github', dest: '.github', type: 'dir' },
  { src: '.propel', dest: '.propel', type: 'dir' },
  { src: '.vscode', dest: '.vscode', type: 'dir' },
  { src: '.env.example', dest: '.env.example', type: 'file' }
];

function copyRecursive(src, dest) {
  const stats = fs.statSync(src);
  
  if (stats.isDirectory()) {
    if (!fs.existsSync(dest)) {
      fs.mkdirSync(dest, { recursive: true });
    }
    
    const entries = fs.readdirSync(src, { withFileTypes: true });
    
    for (const entry of entries) {
      const srcPath = path.join(src, entry.name);
      const destPath = path.join(dest, entry.name);
      
      if (entry.isDirectory()) {
        copyRecursive(srcPath, destPath);
      } else {
        fs.copyFileSync(srcPath, destPath);
      }
    }
  } else {
    fs.copyFileSync(src, dest);
  }
}

function init() {
  console.log('PropelSDLC Copilot Stub Installer');
  console.log('Copyright (c) 2026 KANINI Software Solutions. All rights reserved.\n');
  console.log('Installing to: ' + TARGET_DIR + '\n');
  
  let copiedCount = 0;
  let skippedCount = 0;
  
  for (const item of ITEMS_TO_COPY) {
    const srcPath = path.join(SOURCE_DIR, item.src);
    const destPath = path.join(TARGET_DIR, item.dest);
    
    if (!fs.existsSync(srcPath)) {
      console.log('[WARNING] Source not found: ' + item.src);
      continue;
    }
    
    if (fs.existsSync(destPath)) {
      console.log('[SKIPPED] Already exists: ' + item.dest);
      skippedCount++;
      continue;
    }
    
    try {
      if (item.type === 'dir') {
        copyRecursive(srcPath, destPath);
      } else {
        fs.copyFileSync(srcPath, destPath);
      }
      console.log('[COPIED] ' + item.dest);
      copiedCount++;
    } catch (error) {
      console.error('[ERROR] Failed to copy ' + item.src + ': ' + error.message);
    }
  }
  
  console.log('\nSummary: ' + copiedCount + ' copied, ' + skippedCount + ' skipped');
  console.log('\nInstallation complete!');
  console.log('Next steps:');
  console.log('  1. Review .env.example and create your .env file');
  console.log('  2. Configure Context7 API key in .vscode/mcp.json');
  console.log('  3. Review and configure MCP servers in .vscode/mcp.json');
  console.log('  4. Check .github/copilot-instructions.md for Copilot configuration');
  console.log('  5. Customize .propel/ files for your project');
  console.log('  6. Install Python dependencies: pip install -r .propel/requirements.txt\n');
}

init();
