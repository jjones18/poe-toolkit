'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
    installPageWorker,
    renewPageWorkerLease,
    updatePageWorkerCooldown,
    disarmPageWorker,
} = require('../page_worker');

function createButton(text) {
    const listing = { textContent: '' };
    return {
        textContent: text,
        disabled: false,
        clicks: 0,
        click() {
            this.clicks += 1;
        },
        closest(selector) {
            return selector === '.resultset' ? listing : null;
        },
    };
}

function withFakeBrowser(options, callback) {
    const original = {
        window: global.window,
        document: global.document,
        MutationObserver: global.MutationObserver,
        setInterval: global.setInterval,
        clearInterval: global.clearInterval,
        dateNow: Date.now,
    };

    const now = { value: options.now ?? 1_000 };
    const buttons = [];
    const intervals = new Map();
    let nextIntervalId = 1;
    let observer = null;

    class FakeMutationObserver {
        constructor(handler) {
            this.handler = handler;
            this.connected = false;
            observer = this;
        }

        observe() {
            this.connected = true;
        }

        disconnect() {
            this.connected = false;
        }
    }

    global.window = {
        location: { href: options.url ?? 'https://www.pathofexile.com/trade/search/Allflame/abc/live' },
    };
    global.document = {
        querySelectorAll(selector) {
            return selector === '.results button' ? buttons : [];
        },
        querySelector(selector) {
            return selector === '.results' ? {} : null;
        },
    };
    global.MutationObserver = FakeMutationObserver;
    global.setInterval = (handler) => {
        const id = nextIntervalId++;
        intervals.set(id, handler);
        return id;
    };
    global.clearInterval = (id) => intervals.delete(id);
    Date.now = () => now.value;

    const controls = {
        now,
        buttons,
        get observer() {
            return observer;
        },
        tickIntervals() {
            for (const handler of [...intervals.values()]) handler();
        },
        intervalCount() {
            return intervals.size;
        },
    };

    try {
        callback(controls);
    } finally {
        global.window = original.window;
        global.document = original.document;
        global.MutationObserver = original.MutationObserver;
        global.setInterval = original.setInterval;
        global.clearInterval = original.clearInterval;
        Date.now = original.dateNow;
    }
}

function installDefaultWorker(overrides = {}) {
    return installPageWorker({
        runId: 'run-1',
        searchId: 'abc',
        cooldownMs: 5_000,
        leaseExpiresAt: 4_000,
        tradePath: '/trade',
        ...overrides,
    });
}

test('expired controller lease prevents a delayed click', () => {
    withFakeBrowser({}, ({ now, buttons, tickIntervals }) => {
        installDefaultWorker();
        const travel = createButton('Travel to Hideout');
        buttons.push(travel);

        now.value = 4_001;
        tickIntervals();

        assert.equal(travel.clicks, 0);
        assert.equal(global.window.poeAutoClicker.running, false);
    });
});

test('paused worker blocks Teleport anyway clicks', () => {
    withFakeBrowser({}, ({ buttons, tickIntervals }) => {
        installDefaultWorker();
        global.window.poeAutoClicker.paused = true;
        const teleport = createButton('Teleport anyway');
        buttons.push(teleport);

        tickIntervals();

        assert.equal(teleport.clicks, 0);
    });
});

test('Teleport anyway remains immediate after this run initiates Travel', () => {
    withFakeBrowser({ now: 6_000 }, ({ buttons, tickIntervals }) => {
        const travel = createButton('Travel to Hideout');
        buttons.push(travel);
        installDefaultWorker({ leaseExpiresAt: 8_000 });

        assert.equal(travel.clicks, 1);
        assert.equal(global.window.poeAutoClicker.paused, true);

        const teleport = createButton('Teleport anyway');
        buttons.splice(0, buttons.length, teleport);
        tickIntervals();

        assert.equal(teleport.clicks, 1);
    });
});

test('worker refuses to click after SPA navigation leaves its live search', () => {
    withFakeBrowser({}, ({ buttons, tickIntervals }) => {
        installDefaultWorker();
        global.window.location.href = 'https://www.pathofexile.com/trade/search/Allflame/other';
        const travel = createButton('Travel to Hideout');
        buttons.push(travel);

        tickIntervals();

        assert.equal(travel.clicks, 0);
        assert.equal(global.window.poeAutoClicker.running, false);
    });
});

test('only the owning run can renew a worker lease', () => {
    withFakeBrowser({}, ({ now, buttons, tickIntervals }) => {
        installDefaultWorker({ leaseExpiresAt: 1_500 });
        assert.equal(renewPageWorkerLease({ runId: 'stale-run', leaseExpiresAt: 8_000 }), false);
        assert.equal(renewPageWorkerLease({ runId: 'run-1', leaseExpiresAt: 8_000 }), true);

        const travel = createButton('Travel to Hideout');
        buttons.push(travel);
        now.value = 6_000;
        tickIntervals();

        assert.equal(travel.clicks, 1);
    });
});

test('only the owning run can update the active click cooldown', () => {
    withFakeBrowser({}, () => {
        installDefaultWorker();

        assert.equal(updatePageWorkerCooldown({ runId: 'stale-run', cooldownMs: 9_000 }), false);
        assert.equal(global.window.poeAutoClicker.cooldownMs, 5_000);

        assert.equal(updatePageWorkerCooldown({ runId: 'run-1', cooldownMs: 9_000 }), true);
        assert.equal(global.window.poeAutoClicker.cooldownMs, 9_000);
    });
});

test('disarm disconnects observer and clears the page-local interval', () => {
    withFakeBrowser({}, (controls) => {
        installDefaultWorker();
        const observer = controls.observer;
        assert.equal(controls.intervalCount(), 1);
        assert.equal(observer.connected, true);

        const result = disarmPageWorker();

        assert.equal(result.disarmed, true);
        assert.equal(global.window.poeAutoClicker.running, false);
        assert.equal(observer.connected, false);
        assert.equal(controls.intervalCount(), 0);
    });
});
