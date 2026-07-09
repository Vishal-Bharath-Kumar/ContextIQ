#!/usr/bin/env node

/**
 * Prepare script - Copies source files into .npm-package for publishing
 * Run before publishing: node prepare.js
 */

const fs = require('fs');
const path = require('path');

const SOURCE_DIR = path.join(__dirname, '..');
const TARGET_DIR = __dirname;

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
  if (fs.existsSync(dir)) {
    fs.rmSync(dir, { recursive: true, force: true });
  }
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
  
  console.log('\n✅ Package prepared successfully!');
  console.log('\nNext steps:');
  console.log('  1. Test: npm pack');
  console.log('  2. Publish: npm publish --access public');
}

prepare();
