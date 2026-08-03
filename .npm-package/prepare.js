#!/usr/bin/env node

/**
 * Prepare script - Copies source files into .npm-package for publishing
 * Run before publishing: node prepare.js
 */

const fs = require('fs');
const path = require('path');

const SOURCE_DIR = path.join(__dirname, '..');
const TARGET_DIR = __dirname;
const MCP_CONFIG_PATH = path.join(TARGET_DIR, '.vscode', 'mcp.json');
const DEFAULT_CONTEXTIQ_AUTHORIZATION = 'Bearer ${env:CONTEXTIQ_TOKEN}';

const ITEMS_TO_COPY = [
  { src: '.github', dest: '.github', type: 'dir' },
  { src: '.vscode', dest: '.vscode', type: 'dir' },
  { src: '.propel', dest: '.propel', type: 'dir' },
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

function deleteRecursive(dir) {
  if (!fs.existsSync(dir)) {
    return;
  }

  const stats = fs.lstatSync(dir);
  if (!stats.isDirectory() || stats.isSymbolicLink()) {
    fs.rmSync(dir, { force: true, maxRetries: 5, retryDelay: 50 });
    return;
  }

  for (const entry of fs.readdirSync(dir)) {
    deleteRecursive(path.join(dir, entry));
  }

  fs.rmdirSync(dir);
}

function sanitizeMcpConfig(filePath) {
  if (!fs.existsSync(filePath)) {
    return;
  }

  const config = JSON.parse(fs.readFileSync(filePath, 'utf8'));
  const contextiqHeaders = config?.servers?.contextiq?.headers;

  if (!contextiqHeaders || typeof contextiqHeaders !== 'object') {
    throw new Error('Could not find servers.contextiq.headers in .vscode/mcp.json');
  }

  contextiqHeaders.Authorization = DEFAULT_CONTEXTIQ_AUTHORIZATION;
  fs.writeFileSync(filePath, JSON.stringify(config, null, 2) + '\n');
  console.log('[SANITIZE] .npm-package/.vscode/mcp.json');
}

function prepare() {
  console.log('Preparing package for publishing...\n');
  
  // Clean existing files first
  for (const item of ITEMS_TO_COPY) {
    const destPath = path.join(TARGET_DIR, item.dest);
    if (fs.existsSync(destPath)) {
      console.log(`[CLEAN] Removing existing ${item.dest}`);
      deleteRecursive(destPath);
    }
  }
  
  // Copy source files
  for (const item of ITEMS_TO_COPY) {
    const srcPath = path.join(SOURCE_DIR, item.src);
    const destPath = path.join(TARGET_DIR, item.dest);
    
    if (!fs.existsSync(srcPath)) {
      console.error(`[ERROR] Source not found: ${item.src}`);
      process.exit(1);
    }
    
    console.log(`[COPY] ${item.src} → .npm-package/${item.dest}`);
    
    if (item.type === 'dir') {
      copyRecursive(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }

  sanitizeMcpConfig(MCP_CONFIG_PATH);
  
  console.log('\n✅ Package prepared successfully!');
  console.log('\nNext steps:');
  console.log('  1. Test: npm pack');
  console.log('  2. Publish: npm publish --access public');
}

prepare();
