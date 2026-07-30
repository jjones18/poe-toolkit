'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');

const {
    DEFAULT_PAGE_POLL_INTERVAL_MS,
    DEFAULT_CONFIRMATION_RETRY_MS,
    CONTROLLER_LEASE_MS,
    LEASE_RENEW_INTERVAL_MS,
    disarmAllBrowserWorkers,
    createLineInput,
    parseRuntimeControl,
    classifyTravelResponse,
    attachTravelResponseLogging,
    detachTravelResponseLogging,
    installMonitoredPageWorker,
    installMonitoredPageSet,
    getActiveRunPages,
    updateActiveWorkerCooldown,
    waitForEnterOrTimeout,
} = require('../trade_monitor');

test('monitoring defaults use the bounded fast click path', () => {
    assert.equal(DEFAULT_PAGE_POLL_INTERVAL_MS, 10);
    assert.equal(DEFAULT_CONFIRMATION_RETRY_MS, 20);
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

test('travel response classifier distinguishes confirmation from accepted teleport', () => {
    assert.deepEqual(classifyTravelResponse(200, { success: false }), {
        kind: 'confirmation-required',
        detail: 'Item is in demand; sending "Teleport anyway" confirmation',
    });
    assert.deepEqual(classifyTravelResponse(200, { success: true }), {
        kind: 'confirmed',
        detail: 'Teleport accepted by Path of Exile',
    });
});

test('travel response classifier reports server rejection details', () => {
    assert.deepEqual(
        classifyTravelResponse(404, {
            error: { code: 1, message: 'The item is no longer available' },
        }),
        {
            kind: 'failed',
            detail: 'HTTP 404: The item is no longer available',
        },
    );
});

test('travel response classifier treats 2xx logical errors as failures', () => {
    assert.deepEqual(
        classifyTravelResponse(200, {
            success: false,
            error: { message: 'The item is no longer available' },
        }),
        {
            kind: 'failed',
            detail: 'HTTP 200: The item is no longer available',
        },
    );
});

test('travel response logger attachment replaces and detaches handlers cleanly', () => {
    const page = new EventEmitter();
    attachTravelResponseLogging(page, 'search-a', 'run-a');
    assert.equal(page.listenerCount('response'), 1);

    attachTravelResponseLogging(page, 'search-a', 'run-a');
    assert.equal(page.listenerCount('response'), 1);

    assert.equal(detachTravelResponseLogging(page), true);
    assert.equal(page.listenerCount('response'), 0);
    assert.equal(detachTravelResponseLogging(page), false);
});

test('failed worker installation removes its response logger', async () => {
    const page = new EventEmitter();
    page.evaluate = async () => {
        throw new Error('navigation race');
    };

    await assert.rejects(
        installMonitoredPageWorker(page, 'search-a', 'run-a', {}, () => true),
        /navigation race/,
    );
    assert.equal(page.listenerCount('response'), 0);
});

test('successful worker installation keeps one response logger', async () => {
    const page = new EventEmitter();
    page.evaluate = async () => ({ installed: true, runId: 'run-a' });

    await installMonitoredPageWorker(page, 'search-a', 'run-a', {}, () => true);
    assert.equal(page.listenerCount('response'), 1);
    detachTravelResponseLogging(page);
});

test('ownership loss during page install detaches logger and disarms only that run', async () => {
    const page = new EventEmitter();
    let active = true;
    const evaluated = [];
    page.evaluate = async (fn) => {
        evaluated.push(fn.name);
        if (fn.name === 'installPageWorker') {
            active = false;
            return { installed: true, runId: 'old-run' };
        }
        return { disarmed: true, runId: 'old-run' };
    };

    const result = await installMonitoredPageWorker(
        page,
        'search-a',
        'old-run',
        { runId: 'old-run', controllerId: 'controller-1', generation: 1 },
        () => active,
    );

    assert.equal(result.stale, true);
    assert.equal(page.listenerCount('response'), 0);
    assert.deepEqual(evaluated, ['installPageWorker', 'disarmPageWorkerForRun']);
});

test('partial multi-page startup rolls back every installed response logger', async () => {
    const first = new EventEmitter();
    first.evaluate = async () => ({ installed: true, runId: 'run-a' });
    const second = new EventEmitter();
    second.evaluate = async () => {
        throw new Error('second tab navigation race');
    };
    const labels = new Map([
        [first, 'search-a'],
        [second, 'search-b'],
    ]);

    await assert.rejects(
        installMonitoredPageSet(
            [first, second],
            labels,
            'run-a',
            searchId => ({ runId: 'run-a', searchId }),
            () => {},
            () => true,
        ),
        /second tab navigation race/,
    );
    assert.equal(first.listenerCount('response'), 0);
    assert.equal(second.listenerCount('response'), 0);
});

test('tab discovery drops pages when run ownership changes during browser lookup', async () => {
    let active = true;
    const page = {};
    const browser = {
        pages: async () => {
            active = false;
            return [page];
        },
    };

    const pages = await getActiveRunPages(browser, 'old-run', () => active);
    assert.equal(pages, null);
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
