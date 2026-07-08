// ============================================================
//  游戏全流程自动化测试 (Puppeteer)
// ============================================================
const puppeteer = require('puppeteer');
const fs = require('fs');

const BASE = 'http://localhost:8765';
const SCREENSHOT_DIR = '/tmp/storymap_test_screenshots';

const results = { passed: [], failed: [], screenshots: [] };

function log(icon, msg) {
  console.log(`  ${icon} ${msg}`);
}

async function test(label, fn) {
  try {
    await fn();
    results.passed.push(label);
    log('✅', label);
  } catch (e) {
    results.failed.push({ label, error: e.message });
    log('❌', `${label} — ${e.message}`);
  }
}

async function screenshot(page, name) {
  const path = `${SCREENSHOT_DIR}/${name}.png`;
  await page.screenshot({ path, fullPage: false });
  results.screenshots.push(path);
}

async function checkConsole(page) {
  const errors = [];
  page.on('console', msg => {
    if (msg.type() === 'error') errors.push(msg.text());
  });
  page.on('pageerror', err => errors.push(err.message));
  // Wait a bit for errors to accumulate
  await new Promise(r => setTimeout(r, 1000));
  return errors;
}

async function run() {
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });

  console.log('\n========================================');
  console.log('  游戏全流程自动化测试');
  console.log('========================================\n');

  const browser = await puppeteer.launch({
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  });

  try {
    // ================================================================
    //  Test 1: 王安石变法
    // ================================================================
    console.log('\n── 1. 王安石变法 song-minister-game ──\n');
    {
      const page = await browser.newPage();
      await page.setViewport({ width: 1280, height: 800 });
      const errors = [];
      page.on('pageerror', err => errors.push(err.message));

      await test('封面页加载', async () => {
        await page.goto(`${BASE}/song-minister-game/index.html`, { waitUntil: 'networkidle0', timeout: 15000 });
        await new Promise(r => setTimeout(r, 1000));
        await screenshot(page, 'song_minister_01_cover');
      });

      await test('封面页无 JS 错误', async () => {
        if (errors.length > 0) throw new Error(`JS errors: ${errors.join('; ')}`);
      });

      await page.close();
    }

  } finally {
    await browser.close();
  }

  // ================================================================
  //  Report
  // ================================================================
  console.log('\n========================================');
  console.log('  测试报告');
  console.log('========================================\n');
  console.log(`  通过: ${results.passed.length}`);
  console.log(`  失败: ${results.failed.length}`);
  console.log(`  截图: ${results.screenshots.length}`);
  console.log();

  if (results.failed.length > 0) {
    console.log('  失败详情:');
    for (const f of results.failed) {
      console.log(`    ❌ ${f.label}`);
      console.log(`       ${f.error}`);
    }
  }

  console.log('\n  截图位置:');
  for (const s of results.screenshots) {
    console.log(`    📸 ${s}`);
  }

  return results.failed.length === 0;
}

run().then(passed => {
  process.exit(passed ? 0 : 1);
}).catch(err => {
  console.error('FATAL:', err.message);
  process.exit(1);
});
