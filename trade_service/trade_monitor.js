/**
 * Path of Exile Trade - Connect to YOUR Existing Browser
 * 
 * This connects to your ALREADY OPEN Brave browser.
 * No automation flags = No Cloudflare detection!
 * 
 * STEP 1: Start Brave with remote debugging (run this in PowerShell):
 *   & "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe" --remote-debugging-port=9222 --user-data-dir="$env:LOCALAPPDATA\poe-toolkit\brave-profile"
 * 
 * STEP 2: In that Brave window, login to PoE and go to your live search
 * 
 * STEP 3: Run this script:
 *   node trade_monitor.js
 */

const puppeteer = require('puppeteer-core');
const { randomUUID } = require('crypto');
const { EventEmitter } = require('events');
const {
    installPageWorker,
    renewPageWorkerLease,
    updatePageWorkerCooldown,
    updatePageWorkerZoneSafety,
    disarmPageWorkerForRun,
    disarmPageWorker,
} = require('./page_worker');
const { ZoneGate } = require('./zone_gate');

const DEFAULT_PAGE_POLL_INTERVAL_MS = 10;
const DEFAULT_CONFIRMATION_RETRY_MS = 20;
const CONTROLLER_LEASE_MS = 5000;
const LEASE_RENEW_INTERVAL_MS = 1000;
const ZONE_STATE_PREFIX = '__POE_TOOLKIT_ZONE_STATE__:';

const runtime = {
    browser: null,
    input: null,
    controllerId: randomUUID(),
    runGeneration: 0,
    activeGeneration: null,
    activeRunId: null,
    monitorTimers: new Set(),
    responseHandlers: new Map(),
    reconnecting: false,
    shuttingDown: false,
    shutdownPromise: null,
    zoneGate: null,
};

function isMonitoringRunActive(runId, generation = null) {
    return !runtime.shuttingDown &&
        runtime.activeRunId === runId &&
        (generation === null || runtime.activeGeneration === generation);
}

async function getActiveRunPages(
    browser,
    runId,
    isActive = isMonitoringRunActive,
) {
    if (!isActive(runId)) return null;
    const pages = await browser.pages();
    return isActive(runId) ? pages : null;
}

function addMonitorInterval(callback, delayMs) {
    const timer = setInterval(callback, delayMs);
    runtime.monitorTimers.add(timer);
    return timer;
}

function clearMonitorTimers() {
    for (const timer of runtime.monitorTimers) clearInterval(timer);
    runtime.monitorTimers.clear();
    for (const page of [...runtime.responseHandlers.keys()]) {
        detachTravelResponseLogging(page);
    }
}

function delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

function createLineInput(source) {
    const input = new EventEmitter();
    let buffer = '';

    source.on('data', (data) => {
        buffer += data.toString();
        let newlineIndex = buffer.indexOf('\n');
        while (newlineIndex !== -1) {
            let line = buffer.slice(0, newlineIndex);
            buffer = buffer.slice(newlineIndex + 1);
            if (line.charCodeAt(line.length - 1) === 13) line = line.slice(0, -1);
            input.emit('data', Buffer.from(line));
            newlineIndex = buffer.indexOf('\n');
        }
    });

    source.on('end', () => {
        if (buffer.length > 0) input.emit('data', Buffer.from(buffer));
        buffer = '';
        // Parent closed the pipe (clean stop or controller death): treat as a
        // shutdown request so the service never outlives its controller.
        input.emit('eof');
    });

    source.on('close', () => {
        if (!input.destroyed) input.emit('eof');
    });

    source.on('error', () => {
        if (!input.destroyed) input.emit('eof');
    });

    return input;
}

async function disarmAllBrowserWorkers(browser) {
    const result = { cleaned: 0, missing: 0, failed: 0 };
    if (!browser) return result;

    let pages;
    try {
        pages = await browser.pages();
    } catch (err) {
        result.failed += 1;
        return result;
    }

    for (const page of pages) {
        try {
            const pageResult = await page.evaluate(disarmPageWorker);
            if (pageResult && pageResult.disarmed) result.cleaned += 1;
            else result.missing += 1;
        } catch (err) {
            result.failed += 1;
        }
    }
    return result;
}

async function shutdownService(reason = 'requested') {
    if (runtime.shutdownPromise) return runtime.shutdownPromise;

    runtime.shutdownPromise = (async () => {
        runtime.shuttingDown = true;
        runtime.activeRunId = null;
        runtime.activeGeneration = null;
        clearMonitorTimers();
        if (runtime.zoneGate) runtime.zoneGate.stop();

        console.log(`\n🛑 Stopping automation (${reason})...`);
        const cleanup = await disarmAllBrowserWorkers(runtime.browser);

        // If CDP cleanup failed, remain alive until every unrenewed page lease
        // has expired. This keeps "Stopped" fail-closed even on disconnect.
        if (cleanup.failed > 0) {
            await delay(CONTROLLER_LEASE_MS + 50);
        }

        if (runtime.browser) {
            try {
                runtime.browser.disconnect();
            } catch (err) {
                // Browser/CDP may already be disconnected. The page lease still fails closed.
            }
        }

        console.log(`SHUTDOWN_COMPLETE cleaned=${cleanup.cleaned} missing=${cleanup.missing} failed=${cleanup.failed} lease_ms=${CONTROLLER_LEASE_MS}`);
        await delay(25);
        process.exit(0);
    })();

    return runtime.shutdownPromise;
}

function getSearchId(url) {
    return url.match(/trade2?\/search\/[^/]+\/([^/]+)/)?.[1] || 'unknown';
}

function getGameConfig(args) {
    const gameArg = args.find(a => a.startsWith('--game='));
    const game = gameArg ? gameArg.split('=')[1] : 'poe1';
    if (game === 'poe2') {
        return { id: 'poe2', label: 'PoE 2', tradePath: '/trade2' };
    }
    return { id: 'poe1', label: 'PoE 1', tradePath: '/trade' };
}

function isLiveTradeUrl(url, tradePath) {
    try {
        const parsed = new URL(url);
        const isPathMatch = parsed.pathname === tradePath || parsed.pathname.startsWith(`${tradePath}/`);
        return parsed.hostname.includes('pathofexile.com') && isPathMatch && parsed.pathname.includes('/live');
    } catch (err) {
        return false;
    }
}

async function connectToBrowser() {
    try {
        const browser = await puppeteer.connect({
            browserURL: 'http://127.0.0.1:9222',
            defaultViewport: null
        });
        return browser;
    } catch (err) {
        return null;
    }
}

// Shared state so stdin updates are visible across monitoring/reconnect lifecycles.
const state = {
    autoResumeEnabled: false,
    autoResumeDelayMs: 60_000,
    cooldownMs: 5_000,
    pollIntervalMs: DEFAULT_PAGE_POLL_INTERVAL_MS,
    confirmationRetryMs: DEFAULT_CONFIRMATION_RETRY_MS,
};

function parseRuntimeControl(message) {
    const zoneMatch = /^__(allow|remove)_zone__:([A-Za-z0-9_]+)$/.exec(message);
    if (zoneMatch) {
        return {
            type: zoneMatch[1] === 'allow' ? 'allowZone' : 'removeZone',
            areaId: zoneMatch[2],
        };
    }
    const match = /^__(auto_resume_delay|cooldown)__:(\d+)$/.exec(message);
    if (!match) return null;

    const seconds = Number.parseInt(match[2], 10);
    if (!Number.isFinite(seconds) || seconds <= 0) return null;

    return {
        type: match[1] === 'auto_resume_delay' ? 'autoResumeDelay' : 'cooldown',
        valueMs: seconds * 1_000,
    };
}

function classifyTravelResponse(status, payload) {
    if (status >= 200 && status < 300 && payload?.success === true) {
        return { kind: 'confirmed', detail: 'Teleport accepted by Path of Exile' };
    }
    const logicalError = payload?.error?.message || payload?.message;
    if (logicalError) {
        return { kind: 'failed', detail: `HTTP ${status}: ${logicalError}` };
    }
    if (status >= 200 && status < 300 && payload?.success === false) {
        return {
            kind: 'confirmation-required',
            detail: 'Item is in demand; sending "Teleport anyway" confirmation',
        };
    }

    const message = payload?.error?.message || payload?.message || 'Request rejected';
    return { kind: 'failed', detail: `HTTP ${status}: ${message}` };
}

function attachTravelResponseLogging(page, searchId, runId) {
    detachTravelResponseLogging(page);

    const handler = async (response) => {
        if (runtime.shuttingDown || runtime.activeRunId !== runId) return;

        let url;
        try {
            url = new URL(response.url());
        } catch (err) {
            return;
        }
        if (url.hostname !== 'www.pathofexile.com' || url.pathname !== '/api/trade/whisper') {
            return;
        }

        let payload = null;
        try {
            payload = await response.json();
        } catch (err) {
            // Status still provides an actionable result when the body is unavailable.
        }
        if (runtime.shuttingDown || runtime.activeRunId !== runId) return;
        const outcome = classifyTravelResponse(response.status(), payload);
        if (outcome.kind === 'confirmed') {
            console.log(`✅ [${searchId}] ${outcome.detail}`);
        } else if (outcome.kind === 'confirmation-required') {
            console.log(`⚠️  [${searchId}] ${outcome.detail}`);
        } else {
            console.log(`❌ [${searchId}] Teleport request failed: ${outcome.detail}`);
        }
    };

    page.on('response', handler);
    runtime.responseHandlers.set(page, handler);
    return handler;
}

function detachTravelResponseLogging(page, expectedHandler = null) {
    const handler = runtime.responseHandlers.get(page);
    if (!handler || (expectedHandler && handler !== expectedHandler)) return false;
    page.off('response', handler);
    runtime.responseHandlers.delete(page);
    return true;
}

async function cleanupStalePageInstall(page, runId, responseHandler) {
    detachTravelResponseLogging(page, responseHandler);
    try {
        await page.evaluate(disarmPageWorkerForRun, runId);
    } catch (error) {
        // A closed/navigating page will fail closed when its short lease expires.
    }
}

async function installMonitoredPageWorker(
    page,
    searchId,
    runId,
    workerOptions,
    isActive = () => isMonitoringRunActive(runId, workerOptions.generation),
) {
    if (!isActive()) return { installed: false, stale: true, runId };
    const responseHandler = attachTravelResponseLogging(page, searchId, runId);
    try {
        const result = await page.evaluate(installPageWorker, workerOptions);
        if (!isActive() || result?.stale || result?.installed !== true) {
            await cleanupStalePageInstall(page, runId, responseHandler);
            return { ...result, installed: false, stale: true, runId };
        }
        return { ...result, responseHandler };
    } catch (error) {
        detachTravelResponseLogging(page, responseHandler);
        if (!isActive()) {
            await cleanupStalePageInstall(page, runId, responseHandler);
            return { installed: false, stale: true, runId };
        }
        throw error;
    }
}

async function installMonitoredPageSet(
    pages,
    tabLabels,
    runId,
    createWorkerOptions,
    onInstalled = () => {},
    isActive = () => isMonitoringRunActive(runId),
) {
    const installedPages = [];
    try {
        for (const page of pages) {
            const searchId = tabLabels.get(page);
            const result = await installMonitoredPageWorker(
                page,
                searchId,
                runId,
                createWorkerOptions(searchId),
                isActive,
            );
            if (!result.installed) {
                throw new Error('Monitoring run was superseded during page installation');
            }
            installedPages.push({ page, responseHandler: result.responseHandler });
            onInstalled(searchId);
        }
        return installedPages.length;
    } catch (error) {
        for (const installed of installedPages) {
            await cleanupStalePageInstall(
                installed.page,
                runId,
                installed.responseHandler,
            );
        }
        throw error;
    }
}

async function renewOrRepairMonitoredPageWorker(
    page,
    searchId,
    runId,
    workerOptions,
    isActive = () => isMonitoringRunActive(runId, workerOptions.generation),
) {
    if (!isActive()) {
        return { renewed: false, repaired: false, reason: 'inactive-run' };
    }
    if (page.isClosed?.()) {
        return { renewed: false, repaired: false, reason: 'page-closed' };
    }

    const url = page.url();
    if (
        !isLiveTradeUrl(url, workerOptions.tradePath) ||
        getSearchId(url) !== searchId
    ) {
        return { renewed: false, repaired: false, reason: 'route-mismatch' };
    }

    let renewed;
    try {
        renewed = await page.evaluate(renewPageWorkerLease, {
            runId,
            leaseExpiresAt: workerOptions.leaseExpiresAt,
            // Heartbeat reconciliation: push the CURRENT gate state so a lost
            // zone-change event cannot leave a stale zoneSafe=true in place.
            zoneSafe: runtime.zoneGate ? runtime.zoneGate.getState().safe : false,
        });
    } catch (err) {
        // A page in the middle of navigation will be retried on the next heartbeat.
        return { renewed: false, repaired: false, reason: 'page-unavailable' };
    }
    if (renewed) {
        return { renewed: true, repaired: false, reason: 'lease-renewed' };
    }
    if (!isActive()) {
        return { renewed: false, repaired: false, reason: 'inactive-run' };
    }

    const result = await installMonitoredPageWorker(
        page,
        searchId,
        runId,
        workerOptions,
        isActive,
    );
    return {
        renewed: false,
        repaired: result.installed === true,
        reason: result.installed === true ? 'worker-missing' : 'repair-rejected',
    };
}

async function updateActiveWorkerCooldown(browser, runId, cooldownMs) {
    if (!browser || !runId) return { updated: 0, failed: 0 };
    const result = { updated: 0, failed: 0 };
    let pages;
    try {
        pages = await browser.pages();
    } catch (err) {
        result.failed += 1;
        return result;
    }

    for (const page of pages) {
        try {
            const updated = await page.evaluate(updatePageWorkerCooldown, { runId, cooldownMs });
            if (updated) result.updated += 1;
        } catch (err) {
            result.failed += 1;
        }
    }
    return result;
}

async function updateActiveWorkerZoneSafety(browser, runId, zoneSafe) {
    if (!browser || !runId) return { updated: 0, failed: 0 };
    const result = { updated: 0, failed: 0 };
    let pages;
    try {
        pages = await browser.pages();
    } catch (err) {
        result.failed += 1;
        return result;
    }

    for (const page of pages) {
        try {
            const updated = await page.evaluate(updatePageWorkerZoneSafety, { runId, zoneSafe });
            if (updated) result.updated += 1;
        } catch (err) {
            result.failed += 1;
        }
    }
    return result;
}

function logZoneGateState(zoneState) {
    if (zoneState.kind === 'disabled') {
        console.log('Zone safety gate disabled.');
    } else if (zoneState.safe) {
        console.log(`🏠 ZONE SAFE: ${zoneState.areaId} (${zoneState.kind}) - clicking enabled`);
    } else if (zoneState.kind === 'missing-log') {
        console.log('⛔ ZONE BLOCKED: Client.txt is not configured or could not be found');
    } else if (zoneState.kind === 'unknown') {
        console.log('⛔ ZONE BLOCKED: current area is unknown; waiting for Client.txt');
    } else {
        console.log(`⛔ ZONE BLOCKED: ${zoneState.areaId || zoneState.kind} is not an allowed town/hideout`);
    }
    console.log(`${ZONE_STATE_PREFIX}${JSON.stringify(zoneState)}`);
}

async function attachBrowser(browser, gameConfig) {
    if (runtime.shuttingDown) return;
    runtime.browser = browser;
    browser.once('disconnected', () => {
        void reconnectBrowser(gameConfig);
    });
    await startMonitoring(browser, gameConfig);
}

async function reconnectBrowser(gameConfig) {
    if (runtime.shuttingDown || runtime.reconnecting) return;

    runtime.reconnecting = true;
    runtime.browser = null;
    runtime.activeRunId = null;
    runtime.activeGeneration = null;
    clearMonitorTimers();

    console.log('\n' + '='.repeat(60));
    console.log('🔌 Browser disconnected!');
    console.log('='.repeat(60));
    console.log('⏳ Waiting for browser to reconnect...');
    console.log('='.repeat(60) + '\n');

    while (!runtime.shuttingDown) {
        await delay(5000);
        if (runtime.shuttingDown) break;

        const browser = await connectToBrowser();
        if (!browser) continue;

        console.log('\n✅ Browser reconnected!');
        console.log('🔄 Restarting monitoring...\n');
        runtime.reconnecting = false;
        await attachBrowser(browser, gameConfig);
        return;
    }

    runtime.reconnecting = false;
}

async function main() {
    const args = process.argv.slice(2);
    const gameConfig = getGameConfig(args);
    state.autoResumeEnabled = args.includes('--auto-resume');
    const zoneGateEnabled = args.includes('--zone-gate');
    const clientLogArg = args.find(a => a.startsWith('--client-log='));
    const clientLogPath = clientLogArg ? clientLogArg.slice('--client-log='.length) : '';
    const allowedAreaIds = args
        .filter(a => a.startsWith('--allowed-zone='))
        .map(a => a.slice('--allowed-zone='.length));

    runtime.zoneGate = new ZoneGate({
        enabled: zoneGateEnabled,
        logPath: clientLogPath,
        gameId: gameConfig.id,
        allowedAreaIds,
    });
    const initialZoneState = runtime.zoneGate.start();
    logZoneGateState(initialZoneState);
    runtime.zoneGate.on('change', zoneState => {
        logZoneGateState(zoneState);
        void updateActiveWorkerZoneSafety(
            runtime.browser,
            runtime.activeRunId,
            zoneState.safe,
        );
    });

    const cooldownArg = args.find(a => a.startsWith('--cooldown='));
    if (cooldownArg) {
        const parsed = Number.parseInt(cooldownArg.split('=')[1], 10);
        if (Number.isFinite(parsed) && parsed > 0) state.cooldownMs = parsed * 1_000;
    }

    const delayArg = args.find(a => a.startsWith('--auto-resume-delay='));
    if (delayArg) {
        const parsed = Number.parseInt(delayArg.split('=')[1], 10);
        if (Number.isFinite(parsed) && parsed > 0) state.autoResumeDelayMs = parsed * 1_000;
    }

    const pollArg = args.find(a => a.startsWith('--poll-interval-ms='));
    if (pollArg) {
        const parsed = Number.parseInt(pollArg.split('=')[1], 10);
        if (Number.isFinite(parsed) && parsed > 0) state.pollIntervalMs = parsed;
    }

    const confirmationArg = args.find(a => a.startsWith('--confirmation-retry-ms='));
    if (confirmationArg) {
        const parsed = Number.parseInt(confirmationArg.split('=')[1], 10);
        if (Number.isFinite(parsed) && parsed > 0) state.confirmationRetryMs = parsed;
    }

    // H4 backstop: verify the parent controller PID periodically. If the
    // Python GUI was SIGKILLed (no stdin close, no signal delivered yet),
    // a vanished controller PID ends the service regardless.
    const parentPidArg = args.find(a => a.startsWith('--controller-pid='));
    if (parentPidArg) {
        const controllerPid = Number.parseInt(parentPidArg.split('=')[1], 10);
        if (Number.isFinite(controllerPid) && controllerPid > 0 && process.platform !== 'win32') {
            const parentWatcher = setInterval(() => {
                try {
                    // process.kill(pid, 0) throws when the PID no longer exists.
                    process.kill(controllerPid, 0);
                } catch (err) {
                    clearInterval(parentWatcher);
                    void shutdownService(`controller pid ${controllerPid} no longer exists`);
                }
            }, 5_000);
            parentWatcher.unref?.();
        }
    }

    // Buffer stdin by line so rapid UI updates cannot be coalesced or split.
    const input = createLineInput(process.stdin);
    runtime.input = input;
    input.on('data', (data) => {
        const msg = data.toString().trim();
        if (msg === '__shutdown__') {
            void shutdownService('GUI request');
        } else if (msg === '__auto_resume__:on') {
            state.autoResumeEnabled = true;
            console.log('Auto-resume toggled ON');
        } else if (msg === '__auto_resume__:off') {
            state.autoResumeEnabled = false;
            console.log('Auto-resume toggled OFF');
        } else {
            const control = parseRuntimeControl(msg);
            if (control?.type === 'autoResumeDelay') {
                state.autoResumeDelayMs = control.valueMs;
                console.log(`Auto-resume delay updated to ${control.valueMs / 1_000}s`);
            } else if (control?.type === 'cooldown') {
                state.cooldownMs = control.valueMs;
                console.log(`Teleport cooldown updated to ${control.valueMs / 1_000}s`);
                void updateActiveWorkerCooldown(
                    runtime.browser,
                    runtime.activeRunId,
                    state.cooldownMs,
                ).then(result => {
                    console.log(`Updated cooldown in ${result.updated} active tab(s)`);
                });
            } else if (control?.type === 'allowZone') {
                if (runtime.zoneGate?.allowArea(control.areaId)) {
                    console.log(`Added ${control.areaId} to the runtime zone allowlist.`);
                }
            } else if (control?.type === 'removeZone') {
                if (runtime.zoneGate?.removeArea(control.areaId)) {
                    console.log(`Removed ${control.areaId} from the runtime zone allowlist.`);
                }
            }
        }
    });

    // Parent pipe closed or errored: the controller is gone or stopping.
    // Shut down so browser workers are always disarmed by a live owner.
    input.on('eof', () => {
        void shutdownService('controller stdin closed');
    });
    
    console.log(`PoE Trade Auto - Connect to Existing Browser (${gameConfig.label})\n`);
    console.log('Attempting to connect to your Brave browser on port 9222...\n');

    let browser = await connectToBrowser();
    
    if (!browser) {
        console.log('Could not connect to browser!');
        console.log('Make sure you started Brave with remote debugging.');
        console.log('\nRun: start_brave_debugging.bat\n');
        process.exit(1);
    }

    console.log('Connected to your Brave browser!\n');

    const cooldownSeconds = state.cooldownMs / 1_000;
    const autoResumeSeconds = state.autoResumeDelayMs / 1_000;
    console.log(
        `Fast click path - ${state.pollIntervalMs}ms fallback poll, ` +
        `${state.confirmationRetryMs}ms confirmation retry\n`,
    );
    if (state.autoResumeEnabled) {
        console.log(`Auto-resume enabled - Will resume after ${autoResumeSeconds}s (cooldown: ${cooldownSeconds}s)\n`);
    } else {
        console.log(`Manual resume only - Press Enter to continue (cooldown: ${cooldownSeconds}s)\n`);
    }

    await attachBrowser(browser, gameConfig);
}


async function startMonitoring(browser, gameConfig) {
    let runId = null;
    let generation = null;
    try {
        clearMonitorTimers();
        runId = randomUUID();
        generation = ++runtime.runGeneration;
        runtime.activeRunId = runId;
        runtime.activeGeneration = generation;
        const pages = await browser.pages();
        
        if (pages.length === 0) {
            console.log('❌ No pages found. Please open a tab in Brave first.');
            process.exit(1);
        }

        // Find ALL PoE trade live search pages
        const tradePages = [];
        const tabLabels = new Map(); // page -> search ID from URL
        for (const p of pages) {
            const url = p.url();
            if (isLiveTradeUrl(url, gameConfig.tradePath)) {
                tradePages.push(p);
                tabLabels.set(p, getSearchId(url));
            }
        }

        const staleCleanup = await disarmAllBrowserWorkers(browser);
        if (staleCleanup.cleaned > 0) {
            console.log(`Cleaned up ${staleCleanup.cleaned} stale browser worker(s).`);
        }

        if (tradePages.length === 0) {
            console.log(`No ${gameConfig.label} trade live search pages found!`);
            console.log('Please open at least one live search tab.');
            process.exit(1);
        }

        console.log(`\nFound ${tradePages.length} live search tab(s)!\n`);
        for (let i = 0; i < tradePages.length; i++) {
            console.log(`   ${i + 1}. ${tabLabels.get(tradePages[i])}`);
        }
        console.log('');

        console.log('='.repeat(60));
        console.log('✅ STARTING AUTOMATION');
        console.log('='.repeat(60));
        console.log(`  Monitoring ${tradePages.length} tab(s) simultaneously`);
        console.log('='.repeat(60) + '\n');

        console.log('✅ Starting multi-tab automation...\n');

        let clickCount = 0;
        let lastNotification = Date.now();

        console.log('👀 Monitoring ALL tabs for new listings...');
        console.log(`🔍 Watching ${tradePages.length} live search(es) simultaneously`);
        console.log('🏠 Will click FIRST item that appears in ANY tab');
        console.log('⏸️  Will PAUSE after each click (press Enter to resume)');
        console.log('⏹️  Press Ctrl+C to stop completely\n');

        const createWorkerOptions = searchId => ({
            runId,
            controllerId: runtime.controllerId,
            generation,
            searchId,
            cooldownMs: state.cooldownMs,
            leaseExpiresAt: Date.now() + CONTROLLER_LEASE_MS,
            tradePath: gameConfig.tradePath,
            pollIntervalMs: state.pollIntervalMs,
            confirmationRetryMs: state.confirmationRetryMs,
            zoneSafe: runtime.zoneGate ? runtime.zoneGate.getState().safe : false,
        });

        // Inject the event-driven worker with a fast renderer-local polling fallback.
        await installMonitoredPageSet(
            tradePages,
            tabLabels,
            runId,
            createWorkerOptions,
            searchId => console.log(`  ${searchId} - monitoring enabled`),
        );

        console.log('\nAll tabs are being monitored!\n');
        console.log('Auto-detecting new tabs every 30 seconds...\n');

        let waitingForResume = false;

        let leaseRenewalInProgress = false;
        addMonitorInterval(async () => {
            if (leaseRenewalInProgress || runtime.shuttingDown || runtime.activeRunId !== runId) return;
            leaseRenewalInProgress = true;
            try {
                for (const page of tradePages) {
                    if (page.isClosed()) continue;
                    try {
                        const searchId = tabLabels.get(page);
                        const result = await renewOrRepairMonitoredPageWorker(
                            page,
                            searchId,
                            runId,
                            createWorkerOptions(searchId),
                            () => isMonitoringRunActive(runId, generation),
                        );
                        if (result.repaired) {
                            console.log(`🔧 ${searchId} - worker restored after page reload`);
                        }
                    } catch (err) {
                        // Navigation or CDP loss: the existing lease expires and fails closed.
                    }
                }
            } finally {
                leaseRenewalInProgress = false;
            }
        }, LEASE_RENEW_INTERVAL_MS);

        // Auto-detect new tabs every 30 seconds
        addMonitorInterval(async () => {
            try {
                const runIsActive = () => isMonitoringRunActive(runId, generation);
                const allPages = await getActiveRunPages(browser, runId, runIsActive);
                if (!allPages) return;
                const pagesToRefresh = [];
                
                // Find new tabs and tabs whose SPA route changed searches.
                for (const p of allPages) {
                    if (!runIsActive()) return;
                    const url = p.url();
                    if (isLiveTradeUrl(url, gameConfig.tradePath)) {
                        const currentSearchId = getSearchId(url);
                        if (!tabLabels.has(p) || tabLabels.get(p) !== currentSearchId) {
                            pagesToRefresh.push(p);
                        }
                    }
                }
                
                if (pagesToRefresh.length > 0) {
                    console.log(`\nDetected ${pagesToRefresh.length} new/changed tab(s)!`);
                    
                    for (const page of pagesToRefresh) {
                        if (!runIsActive()) return;
                        const searchId = getSearchId(page.url());
                        const wasTracked = tradePages.includes(page);
                        const previousSearchId = tabLabels.get(page);
                        if (!wasTracked) tradePages.push(page);
                        tabLabels.set(page, searchId);
                        
                        console.log(`   Adding: ${searchId}`);
                        const result = await installMonitoredPageWorker(
                            page,
                            searchId,
                            runId,
                            createWorkerOptions(searchId),
                            runIsActive,
                        );
                        if (!result.installed || !runIsActive()) {
                            if (!wasTracked) {
                                const index = tradePages.indexOf(page);
                                if (index !== -1) tradePages.splice(index, 1);
                            }
                            if (previousSearchId === undefined) tabLabels.delete(page);
                            else tabLabels.set(page, previousSearchId);
                            return;
                        }
                        
                        console.log(`   ${searchId} - monitoring enabled`);
                    }
                    
                    console.log(`\nNow monitoring ${tradePages.length} total tab(s)\n`);
                }
            } catch (err) {
                // Ignore errors during tab detection
            }
        }, 30000); // Check every 30 seconds

        // Monitor clicks and pause state across ALL tabs
        addMonitorInterval(async () => {
            try {
                // Check all tabs for clicks and pause state
                let anyPaused = false;
                let totalClicks = 0;
                let activeWorkerCount = 0;
                let pausedSearchId = '';
                const closedPages = [];
                
                for (let i = 0; i < tradePages.length; i++) {
                    const page = tradePages[i];
                    
                    if (page.isClosed()) {
                        closedPages.push(i);
                        continue;
                    }
                    
                    try {
                        const status = await page.evaluate((expectedRunId) => {
                            const worker = window.poeAutoClicker;
                            const isCurrentRun = Boolean(
                                worker && worker.running && worker.runId === expectedRunId
                            );
                            return {
                                isCurrentRun,
                                clickCount: isCurrentRun ? worker.clickCount : 0,
                                isPaused: isCurrentRun ? worker.paused : false,
                                searchId: isCurrentRun ? worker.searchId : ''
                            };
                        }, runId);
                        
                        totalClicks += status.clickCount;
                        if (status.isCurrentRun) activeWorkerCount += 1;
                        
                        if (status.isPaused) {
                            anyPaused = true;
                            pausedSearchId = tabLabels.get(page) || status.searchId;
                        }
                    } catch (err) {
                        closedPages.push(i);
                    }
                }
                
                if (closedPages.length > 0) {
                    for (let i = closedPages.length - 1; i >= 0; i--) {
                        const index = closedPages[i];
                        const closedPage = tradePages[index];
                        detachTravelResponseLogging(closedPage);
                        tabLabels.delete(closedPage);
                        tradePages.splice(index, 1);
                    }
                    console.log(`\nRemoved ${closedPages.length} closed tab(s)`);
                    console.log(`Now monitoring ${tradePages.length} tab(s)\n`);
                }

                // Check if just clicked (count increased)
                if (totalClicks > clickCount) {
                    const newClicks = totalClicks - clickCount;
                    console.log(`✨ Clicked ${newClicks} item(s)! Total clicks: ${totalClicks}`);
                    clickCount = totalClicks;
                }

                if (anyPaused && !waitingForResume) {
                    waitingForResume = true;
                    console.log('\n' + '='.repeat(60));
                    console.log('PAUSED');
                    console.log('='.repeat(60));
                    console.log(`  Clicked item in search: ${pausedSearchId}`);
                    console.log('  -> Press ENTER to resume monitoring ALL tabs');
                    if (state.autoResumeEnabled) {
                        console.log(`  -> OR wait ${state.autoResumeDelayMs / 1_000} seconds for auto-resume`);
                    }
                    console.log('='.repeat(60) + '\n');
                    
                    const getAutoResume = () => state.autoResumeEnabled;
                    const getAutoResumeDelay = () => state.autoResumeDelayMs;
                    const input = runtime.input || process.stdin;
                    if (state.autoResumeEnabled) {
                        await waitForEnterOrTimeout(
                            getAutoResume,
                            getAutoResumeDelay,
                            5000,
                            input,
                        );
                    } else {
                        await waitForEnter(
                            getAutoResume,
                            getAutoResumeDelay,
                            5000,
                            input,
                        );
                    }
                    
                    if (runtime.shuttingDown || runtime.activeRunId !== runId) return;

                    for (const page of tradePages) {
                        try {
                            if (!page.isClosed()) {
                                await page.evaluate((expectedRunId) => {
                                    if (window.poeAutoClicker?.runId === expectedRunId) {
                                        window.poeAutoClicker.paused = false;
                                        window.poeAutoClicker.isClicking = false;
                                        window.poeAutoClicker.pendingConfirmation = false;
                                        window.poeAutoClicker.pendingListing = null;
                                    }
                                }, runId);
                            }
                        } catch (err) {
                            // Page may have closed
                        }
                    }
                    
                    console.log(`RESUMED - Monitoring all ${tradePages.length} tabs...\n`);
                    waitingForResume = false;
                }

                // Periodic status update (only when not paused)
                if (!anyPaused && Date.now() - lastNotification > 30000) {
                    const monitoredTabs = activeWorkerCount === tradePages.length
                        ? `${activeWorkerCount}`
                        : `${activeWorkerCount}/${tradePages.length}`;
                    console.log(`📊 Status: Monitoring ${monitoredTabs} tabs | Clicks: ${clickCount} | ${new Date().toLocaleTimeString()}`);
                    lastNotification = Date.now();
                }
            } catch (err) {
                console.log('⚠️  Lost connection to page');
            }
        }, 500);

    } catch (err) {
        if (runtime.activeRunId === runId) {
            runtime.activeRunId = null;
            runtime.activeGeneration = null;
            clearMonitorTimers();
        }
        console.error('❌ Error during monitoring:', err.message);
        console.log('⚠️  Monitoring stopped. Script will continue running.');
        console.log('    Waiting for browser reconnect...\n');
    }
}

function waitForEnter(
    getAutoResume,
    getAutoResumeDelay,
    heartbeatIntervalMs = 5000,
    input = process.stdin,
) {
    return new Promise((resolve) => {
        let heartbeatTimer = null;
        let elapsed = 0;
        let dataListener;

        function cleanup() {
            if (heartbeatTimer) clearInterval(heartbeatTimer);
            if (dataListener) input.removeListener('data', dataListener);
        }

        dataListener = (data) => {
            const msg = data.toString().trim();
            if (msg.startsWith('__')) return;
            cleanup();
            console.log('Enter pressed - resuming...');
            resolve('enter');
        };
        input.on('data', dataListener);

        heartbeatTimer = setInterval(() => {
            elapsed += heartbeatIntervalMs;

            // If auto-resume was toggled on while waiting, switch to timed mode
            if (getAutoResume && getAutoResume()) {
                cleanup();
                console.log('Auto-resume enabled mid-pause, switching to timed wait...');
                waitForEnterOrTimeout(
                    getAutoResume,
                    getAutoResumeDelay,
                    heartbeatIntervalMs,
                    input,
                ).then(resolve);
                return;
            }

            const waitSec = Math.floor(elapsed / 1000);
            console.log(`PAUSED - waiting for manual resume... (${waitSec}s elapsed)`);
        }, heartbeatIntervalMs);
    });
}

function waitForEnterOrTimeout(
    getAutoResume,
    getAutoResumeDelay,
    heartbeatIntervalMs = 5000,
    input = process.stdin,
) {
    return new Promise((resolve) => {
        let heartbeatTimer = null;
        let activeElapsed = 0;
        let dataListener;

        function cleanup() {
            if (heartbeatTimer) clearInterval(heartbeatTimer);
            if (dataListener) input.removeListener('data', dataListener);
        }

        dataListener = (data) => {
            const msg = data.toString().trim();
            if (msg.startsWith('__')) return;
            cleanup();
            console.log('Enter pressed - resuming...');
            resolve('enter');
        };
        input.on('data', dataListener);

        heartbeatTimer = setInterval(() => {
            if (getAutoResume()) {
                activeElapsed += heartbeatIntervalMs;
                const autoResumeDelayMs = getAutoResumeDelay();
                const remaining = Math.max(0, Math.ceil((autoResumeDelayMs - activeElapsed) / 1000));

                if (activeElapsed >= autoResumeDelayMs) {
                    cleanup();
                    console.log('Auto-resume timer elapsed - resuming...');
                    resolve('timeout');
                } else {
                    console.log(`PAUSED - auto-resuming in ${remaining}s...`);
                }
            } else {
                console.log('PAUSED - auto-resume disabled, waiting for manual resume...');
            }
        }, heartbeatIntervalMs);
    });
}

if (require.main === module) {
    for (const signalName of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
        process.once(signalName, () => {
            void shutdownService(signalName);
        });
    }

    main().catch((error) => {
        console.error('❌ Error:', error);
        process.exit(1);
    });
}

module.exports = {
    DEFAULT_PAGE_POLL_INTERVAL_MS,
    DEFAULT_CONFIRMATION_RETRY_MS,
    CONTROLLER_LEASE_MS,
    LEASE_RENEW_INTERVAL_MS,
    ZONE_STATE_PREFIX,
    disarmAllBrowserWorkers,
    createLineInput,
    parseRuntimeControl,
    classifyTravelResponse,
    attachTravelResponseLogging,
    detachTravelResponseLogging,
    installMonitoredPageWorker,
    installMonitoredPageSet,
    renewOrRepairMonitoredPageWorker,
    getActiveRunPages,
    updateActiveWorkerCooldown,
    updateActiveWorkerZoneSafety,
    waitForEnterOrTimeout,
};


