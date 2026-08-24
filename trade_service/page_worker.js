'use strict';

/**
 * Install the browser-resident portion of the Trade Sniper.
 *
 * This function is intentionally self-contained because Puppeteer serializes it
 * into the page with page.evaluate(). The worker is fail-closed: it may click
 * only while its owning controller run keeps a short lease alive.
 */
function installPageWorker(options) {
    const existing = window.poeAutoClicker;
    const isOlderControllerGeneration = Boolean(
        existing &&
        existing.controllerId === options.controllerId &&
        Number.isFinite(existing.generation) &&
        Number.isFinite(options.generation) &&
        options.generation < existing.generation
    );
    if (isOlderControllerGeneration) {
        return {
            installed: false,
            stale: true,
            runId: options.runId,
            activeRunId: existing.runId,
        };
    }

    if (existing) {
        existing.running = false;
        existing.paused = true;
        existing.pendingConfirmation = false;
        if (existing.observer) existing.observer.disconnect();
        if (existing.intervalId) clearInterval(existing.intervalId);
    }

    const state = {
        running: true,
        paused: false,
        clickCount: 0,
        observer: null,
        intervalId: null,
        lastClickTime: 0,
        cooldownMs: options.cooldownMs,
        isClicking: false,
        pendingConfirmation: false,
        pendingListing: null,
        confirmationRetryMs: options.confirmationRetryMs || 20,
        lastConfirmationClickTime: Number.NEGATIVE_INFINITY,
        searchId: options.searchId,
        runId: options.runId,
        controllerId: options.controllerId,
        generation: options.generation,
        leaseExpiresAt: options.leaseExpiresAt,
        tradePath: options.tradePath,
        zoneSafe: options.zoneSafe === true,
        maxClicksPerListing: 3,
        listingClicks: new WeakMap(),
    };
    window.poeAutoClicker = state;

    function disarm() {
        state.running = false;
        state.paused = true;
        state.isClicking = false;
        state.pendingConfirmation = false;
        state.pendingListing = null;
        if (state.observer) {
            state.observer.disconnect();
            state.observer = null;
        }
        if (state.intervalId) {
            clearInterval(state.intervalId);
            state.intervalId = null;
        }
    }

    function isExpectedLiveSearch() {
        try {
            const parsed = new URL(window.location.href);
            const expectedSuffix = `/${state.searchId}/live`;
            return parsed.hostname.endsWith('pathofexile.com') &&
                parsed.pathname.startsWith(`${state.tradePath}/search/`) &&
                parsed.pathname.endsWith(expectedSuffix);
        } catch (err) {
            return false;
        }
    }

    function hasLiveControllerLease() {
        if (!state.running) return false;
        if (Date.now() > state.leaseExpiresAt || !isExpectedLiveSearch()) {
            disarm();
            return false;
        }
        return true;
    }

    function getListingClicks(listing) {
        return listing ? (state.listingClicks.get(listing) || 0) : 0;
    }

    function addListingClick(listing) {
        if (!listing) return 0;
        const count = getListingClicks(listing) + 1;
        state.listingClicks.set(listing, count);
        return count;
    }

    function isListingMaxed(listing) {
        return listing && getListingClicks(listing) >= state.maxClicksPerListing;
    }

    function clickTeleportAnyway() {
        if (!hasLiveControllerLease() || !state.zoneSafe || !state.pendingConfirmation || state.isClicking) {
            return false;
        }

        const now = Date.now();
        if (now - state.lastConfirmationClickTime < state.confirmationRetryMs) {
            return false;
        }

        const buttons = document.querySelectorAll('.results button');
        for (let i = 0; i < buttons.length; i++) {
            const button = buttons[i];
            const text = (button.textContent || '').toLowerCase();
            if (!text.includes('teleport') || !text.includes('anyway')) continue;

            const listing = button.closest('.resultset');
            if (!listing || listing !== state.pendingListing || button.disabled) continue;
            if (isListingMaxed(listing)) continue;

            state.isClicking = true;
            try {
                button.click();
                state.lastConfirmationClickTime = now;
                const count = addListingClick(listing);
                console.log(`[${state.searchId}] Clicked "Teleport anyway" (${count}/${state.maxClicksPerListing})`);
                return true;
            } finally {
                state.isClicking = false;
            }
        }
        return false;
    }

    function clickTopTravelButton() {
        if (!hasLiveControllerLease()) return false;
        if (!state.zoneSafe) return false;

        // A confirmation is allowed while paused only when this run initiated it.
        if (clickTeleportAnyway()) return true;
        if (state.paused || state.isClicking) return false;

        const now = Date.now();
        if (now - state.lastClickTime < state.cooldownMs) return false;

        state.isClicking = true;
        try {
            const buttons = document.querySelectorAll('.results button');
            for (let i = 0; i < buttons.length; i++) {
                const button = buttons[i];
                const listing = button.closest('.resultset');
                if (isListingMaxed(listing)) continue;

                const text = button.textContent;
                if (text.indexOf('ravel') === -1) continue;

                const lower = text.toLowerCase();
                if (!(lower.includes('travel') && lower.includes('hideout'))) continue;

                if (button.disabled) {
                    if (listing) addListingClick(listing);
                    continue;
                }

                if (listing) {
                    const listingText = listing.textContent;
                    if (listingText.includes('no longer available') || listingText.includes('is outdated')) {
                        state.listingClicks.set(listing, state.maxClicksPerListing);
                        continue;
                    }
                }

                addListingClick(listing);
                state.lastClickTime = now;
                state.paused = true;
                state.pendingConfirmation = true;
                state.pendingListing = listing;
                button.click();
                state.clickCount += 1;
                console.log(`[${state.searchId}] Clicked item #${state.clickCount}`);
                return true;
            }
            return false;
        } catch (err) {
            return false;
        } finally {
            state.isClicking = false;
        }
    }

    const observer = new MutationObserver(() => {
        clickTopTravelButton();
    });

    const resultsContainer = document.querySelector('.results');
    if (resultsContainer) {
        observer.observe(resultsContainer, {
            childList: true,
            subtree: true,
            attributes: true,
            characterData: true,
        });
        state.observer = observer;
    }

    state.intervalId = setInterval(clickTopTravelButton, options.pollIntervalMs || 10);
    clickTopTravelButton();

    return { installed: true, runId: state.runId, searchId: state.searchId };
}

/** Renew a worker only when it is still owned by this controller run. */
function renewPageWorkerLease(options) {
    const state = window.poeAutoClicker;
    if (!state || !state.running || state.runId !== options.runId) return false;
    state.leaseExpiresAt = options.leaseExpiresAt;
    // Reconcile zone safety on every heartbeat. If a zone-gate 'change' push
    // was lost (CDP hiccup mid-navigation), the next renewal corrects it
    // instead of letting a stale zoneSafe=true survive indefinitely.
    if (typeof options.zoneSafe === 'boolean') {
        state.zoneSafe = options.zoneSafe;
    }
    return true;
}

/** Update cooldown only when this worker is owned by the current controller run. */
function updatePageWorkerCooldown(options) {
    const state = window.poeAutoClicker;
    if (!state || !state.running || state.runId !== options.runId) return false;
    if (!Number.isFinite(options.cooldownMs) || options.cooldownMs <= 0) return false;
    state.cooldownMs = options.cooldownMs;
    return true;
}

/** Update zone safety only when this worker belongs to the current controller run. */
function updatePageWorkerZoneSafety(options) {
    const state = window.poeAutoClicker;
    if (!state || !state.running || state.runId !== options.runId) return false;
    state.zoneSafe = options.zoneSafe === true;
    return true;
}

/** Disarm a worker only when it still belongs to the expected controller run. */
function disarmPageWorkerForRun(expectedRunId) {
    const state = window.poeAutoClicker;
    if (!state) return { disarmed: false, reason: 'not-installed' };
    if (state.runId !== expectedRunId) {
        return { disarmed: false, reason: 'ownership-mismatch', runId: state.runId };
    }

    state.running = false;
    state.paused = true;
    state.isClicking = false;
    state.pendingConfirmation = false;
    state.pendingListing = null;
    if (state.observer) {
        state.observer.disconnect();
        state.observer = null;
    }
    if (state.intervalId) {
        clearInterval(state.intervalId);
        state.intervalId = null;
    }
    return { disarmed: true, runId: state.runId, searchId: state.searchId };
}

/** Unconditionally disarm any Trade Sniper worker in the current page. */
function disarmPageWorker() {
    const state = window.poeAutoClicker;
    if (!state) return { disarmed: false, reason: 'not-installed' };

    state.running = false;
    state.paused = true;
    state.isClicking = false;
    state.pendingConfirmation = false;
    state.pendingListing = null;
    if (state.observer) {
        state.observer.disconnect();
        state.observer = null;
    }
    if (state.intervalId) {
        clearInterval(state.intervalId);
        state.intervalId = null;
    }
    return { disarmed: true, runId: state.runId, searchId: state.searchId };
}

module.exports = {
    installPageWorker,
    renewPageWorkerLease,
    updatePageWorkerCooldown,
    updatePageWorkerZoneSafety,
    disarmPageWorkerForRun,
    disarmPageWorker,
};
