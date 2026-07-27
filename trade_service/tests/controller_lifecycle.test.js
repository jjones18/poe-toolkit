'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');

const {
    PAGE_POLL_INTERVAL_MS,
    CONTROLLER_LEASE_MS,
    LEASE_RENEW_INTERVAL_MS,
    disarmAllBrowserWorkers,
    createLineInput,
    parseRuntimeControl,
    updateActiveWorkerCooldown,
    waitForEnterOrTimeout,
} = require('../trade_monitor');

test('refactor preserves established monitoring timing', () => {
    assert.equal(PAGE_POLL_INTERVAL_MS, 50);
    assert.equal(LEASE_RENEW_INTERVAL_MS, 1_000);
    assert.equal(CONTROLLER_LEASE_MS, 5_000);
});

test('shutdown cleanup reports cleaned, missing, and failed pages', async () => {
    const pages = [
        { evaluate: async () => ({ disarmed: true }) },
        { evaluate: async () => ({ disarmed: false }) },
        { evaluate: async () => { throw new Error('CDP unavailable'); } },
    ];
    const browser = { pages: async () => pages };

    const result = await disarmAllBrowserWorkers(browser);

    assert.deepEqual(result, { cleaned: 1, missing: 1, failed: 1 });
});

test('shutdown cleanup fails closed when browser page enumeration is unavailable', async () => {
    const browser = { pages: async () => { throw new Error('browser disconnected'); } };

    const result = await disarmAllBrowserWorkers(browser);

    assert.deepEqual(result, { cleaned: 0, missing: 0, failed: 1 });
});

test('runtime control parser accepts timing updates in seconds', () => {
    assert.deepEqual(parseRuntimeControl('__auto_resume_delay__:17'), {
        type: 'autoResumeDelay',
        valueMs: 17_000,
    });
    assert.deepEqual(parseRuntimeControl('__cooldown__:9'), {
        type: 'cooldown',
        valueMs: 9_000,
    });
    assert.equal(parseRuntimeControl('__auto_resume_delay__:0'), null);
    assert.equal(parseRuntimeControl('__cooldown__:not-a-number'), null);
});

test('stdin line input separates coalesced runtime updates', () => {
    const source = new EventEmitter();
    const input = createLineInput(source);
    const lines = [];
    input.on('data', data => lines.push(data.toString()));

    source.emit('data', Buffer.from('__cooldown__:8\n__auto_resume_delay__:'));
    source.emit('data', Buffer.from('45\n\n'));

    assert.deepEqual(lines, ['__cooldown__:8', '__auto_resume_delay__:45', '']);
});

test('runtime cooldown update reaches active pages and reports failures', async () => {
    const calls = [];
    const pages = [
        {
            evaluate: async (_fn, options) => {
                calls.push(options);
                return true;
            },
        },
        { evaluate: async () => false },
        { evaluate: async () => { throw new Error('page unavailable'); } },
    ];

    const result = await updateActiveWorkerCooldown(
        { pages: async () => pages },
        'run-7',
        8_000,
    );

    assert.deepEqual(calls, [{ runId: 'run-7', cooldownMs: 8_000 }]);
    assert.deepEqual(result, { updated: 1, failed: 1 });
});

test('active auto-resume wait uses an updated delay on its next heartbeat', async () => {
    let delayMs = 60_000;
    const input = new EventEmitter();
    const wait = waitForEnterOrTimeout(
        () => true,
        () => delayMs,
        5,
        input,
    );

    await new Promise(resolve => setTimeout(resolve, 8));
    delayMs = 10;

    const result = await Promise.race([
        wait,
        new Promise((_, reject) => setTimeout(() => reject(new Error('wait did not update')), 100)),
    ]);
    assert.equal(result, 'timeout');
});
