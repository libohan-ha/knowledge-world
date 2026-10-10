import {defineConfig, devices} from '@playwright/test'

export default defineConfig({
  testDir: './e2e', fullyParallel: false, workers: 1, retries: 0,
  timeout: 300_000, expect: {timeout: 15_000},
  outputDir: '../artifacts/refactor/browser-results',
  reporter: [['list'], ['junit', {outputFile: '../artifacts/refactor/browser-tests.xml'}], ['html', {outputFolder: '../artifacts/refactor/browser-report', open: 'never'}]],
  use: {trace: 'on', screenshot: 'only-on-failure', video: 'on', locale: 'zh-CN', timezoneId: 'Asia/Shanghai', actionTimeout: 15_000, navigationTimeout: 30_000, launchOptions:{args:['--use-angle=d3d11']}},
  projects: [
    {name: 'desktop', use: {viewport: {width: 1440, height: 900}}},
    {name: 'mobile', use: {...devices['iPhone 13'], defaultBrowserType: 'chromium', viewport: {width: 390, height: 844}}},
  ],
})
