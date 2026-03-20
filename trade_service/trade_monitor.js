/**
 * Path of Exile Trade - Connect to YOUR Existing Browser
 * 
 * This connects to your ALREADY OPEN Brave browser.
 * No automation flags = No Cloudflare detection!
 * 
 * STEP 1: Start Brave with remote debugging (run this in PowerShell):
 *   & "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe" --remote-debugging-port=9222 --user-data-dir="E:\Git\PoE Trade Automation\brave-profile"
 * 
 * STEP 2: In that Brave window, login to PoE and go to your live search
 * 
 * STEP 3: Run this script:
 *   node poe_trade_connect_existing.js
 */

const puppeteer = require('puppeteer-core');

const CHECK_INTERVAL = 10; // 10ms = checking 100 times per second!

function getSearchId(url) {
    return url.match(/trade\/search\/[^/]+\/([^/]+)/)?.[1] || 'unknown';
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

// Shared state so stdin toggles are visible inside startMonitoring
const state = { autoResumeEnabled: false };

async function main() {
    const args = process.argv.slice(2);
    state.autoResumeEnabled = args.includes('--auto-resume');

    // Parse --cooldown=N (seconds), default 5
    let cooldownSeconds = 5;
    const cooldownArg = args.find(a => a.startsWith('--cooldown='));
    if (cooldownArg) {
        const parsed = parseInt(cooldownArg.split('=')[1], 10);
        if (!isNaN(parsed) && parsed > 0) {
            cooldownSeconds = parsed;
        }
    }
    const cooldownMs = cooldownSeconds * 1000;

    // Listen for dynamic auto-resume toggle commands on stdin
    process.stdin.on('data', (data) => {
        const msg = data.toString().trim();
        if (msg === '__auto_resume__:on') {
            state.autoResumeEnabled = true;
            console.log('Auto-resume toggled ON');
        } else if (msg === '__auto_resume__:off') {
            state.autoResumeEnabled = false;
            console.log('Auto-resume toggled OFF');
        }
    });
    
    console.log('PoE Trade Auto - Connect to Existing Browser\n');
    console.log('Attempting to connect to your Brave browser on port 9222...\n');

    let browser = await connectToBrowser();
    
    if (!browser) {
        console.log('Could not connect to browser!');
        console.log('Make sure you started Brave with remote debugging.');
        console.log('\nRun: start_brave_debugging.bat\n');
        process.exit(1);
    }

    console.log('Connected to your Brave browser!\n');

    if (state.autoResumeEnabled) {
        console.log(`Auto-resume enabled - Will resume after 60s (cooldown: ${cooldownSeconds}s)\n`);
    } else {
        console.log(`Manual resume only - Press Enter to continue (cooldown: ${cooldownSeconds}s)\n`);
    }

    // Listen for browser disconnect
    browser.on('disconnected', async () => {
        console.log('\n' + '='.repeat(60));
        console.log('🔌 Browser disconnected!');
        console.log('='.repeat(60));
        console.log('⏳ Waiting for browser to reconnect...');
        console.log('   Run start_brave_debugging.bat to reconnect');
        console.log('='.repeat(60) + '\n');

        // Try to reconnect every 5 seconds
        const reconnectInterval = setInterval(async () => {
            const newBrowser = await connectToBrowser();
            if (newBrowser) {
                clearInterval(reconnectInterval);
                console.log('\n✅ Browser reconnected!');
                console.log('🔄 Restarting monitoring...\n');
                
                browser = newBrowser;
                
                // Re-attach disconnect listener
                browser.on('disconnected', async () => {
                    console.log('\n' + '='.repeat(60));
                    console.log('🔌 Browser disconnected!');
                    console.log('='.repeat(60));
                    console.log('⏳ Waiting for browser to reconnect...');
                    console.log('   Run start_brave_debugging.bat to reconnect');
                    console.log('='.repeat(60) + '\n');
                    
                    // Recursive reconnect
                    await waitForReconnect();
                });
                
                await startMonitoring(browser, cooldownMs);
            }
        }, 5000);
        
        async function waitForReconnect() {
            const reconnectInterval = setInterval(async () => {
                const newBrowser = await connectToBrowser();
                if (newBrowser) {
                    clearInterval(reconnectInterval);
                    console.log('\n✅ Browser reconnected!');
                    console.log('🔄 Restarting monitoring...\n');
                    
                    browser = newBrowser;
                    browser.on('disconnected', waitForReconnect);
                    await startMonitoring(browser, cooldownMs);
                }
            }, 5000);
        }
    });

    await startMonitoring(browser, cooldownMs);
}


async function startMonitoring(browser, cooldownMs) {
    try {
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
            if (url.includes('pathofexile.com/trade') && url.includes('/live')) {
                tradePages.push(p);
                tabLabels.set(p, getSearchId(url));
            }
        }

        if (tradePages.length === 0) {
            console.log('No PoE trade live search pages found!');
            console.log('Please open at least one live search tab.');
            process.exit(1);
        }

        // Clean up any orphaned in-page scripts from a previous session
        for (const page of tradePages) {
            try {
                await page.evaluate(() => {
                    if (window.poeAutoClicker) {
                        window.poeAutoClicker.running = false;
                        if (window.poeAutoClicker.observer) {
                            window.poeAutoClicker.observer.disconnect();
                        }
                        window.poeAutoClicker = null;
                    }
                });
            } catch (err) {
                // Page may have navigated away
            }
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

        // Inject monitoring script into ALL tabs
        for (let i = 0; i < tradePages.length; i++) {
            const page = tradePages[i];
            const searchId = tabLabels.get(page);
            
            await page.evaluate((checkInterval, searchId, cdMs) => {
            if (window.poeAutoClicker && window.poeAutoClicker.running) {
                window.poeAutoClicker.running = false;
                if (window.poeAutoClicker.observer) {
                    window.poeAutoClicker.observer.disconnect();
                }
            }

            window.poeAutoClicker = {
                running: true,
                paused: false,
                clickCount: 0,
                observer: null,
                lastClickTime: 0,
                cooldownMs: cdMs,
                isClicking: false,
                searchId: searchId,
                maxClicksPerListing: 3,
                listingClicks: new WeakMap()
            };

            function getListingClicks(listing) {
                return listing ? (window.poeAutoClicker.listingClicks.get(listing) || 0) : 0;
            }

            function addListingClick(listing) {
                if (!listing) return 0;
                const count = getListingClicks(listing) + 1;
                window.poeAutoClicker.listingClicks.set(listing, count);
                return count;
            }

            function isListingMaxed(listing) {
                return listing && getListingClicks(listing) >= window.poeAutoClicker.maxClicksPerListing;
            }

            function clickTeleportAnyway() {
                const buttons = document.querySelectorAll('.results button');
                for (let i = 0; i < buttons.length; i++) {
                    const text = buttons[i].textContent;
                    if (text.indexOf('eleport') === -1 || text.indexOf('anyway') === -1) {
                        continue;
                    }
                    const listing = buttons[i].closest('.resultset');
                    if (isListingMaxed(listing)) {
                        continue;
                    }
                    buttons[i].click();
                    const count = addListingClick(listing);
                    console.log(`[${searchId}] Clicked "Teleport anyway" (${count}/${window.poeAutoClicker.maxClicksPerListing})`);
                    return true;
                }
                return false;
            }

            function clickTopTravelButton() {
                if (window.poeAutoClicker.isClicking) {
                    return false;
                }

                if (clickTeleportAnyway()) {
                    return true;
                }

                if (window.poeAutoClicker.paused) {
                    return false;
                }

                const now = Date.now();
                if (now - window.poeAutoClicker.lastClickTime < window.poeAutoClicker.cooldownMs) {
                    return false;
                }

                window.poeAutoClicker.isClicking = true;

                try {
                    const buttons = document.querySelectorAll('.results button');

                    for (let i = 0; i < buttons.length; i++) {
                        const button = buttons[i];
                        const listing = button.closest('.resultset');

                        if (isListingMaxed(listing)) {
                            continue;
                        }

                        const text = button.textContent;

                        if (text.indexOf('ravel') === -1) {
                            continue;
                        }

                        const lower = text.toLowerCase();
                        if (!(lower.includes('travel') && lower.includes('hideout'))) {
                            continue;
                        }

                        if (button.disabled) {
                            if (listing) addListingClick(listing);
                            continue;
                        }

                        if (listing) {
                            const lt = listing.textContent;
                            if (lt.includes('no longer available') ||
                                lt.includes('is outdated')) {
                                // Max it out immediately so we never retry
                                if (listing) window.poeAutoClicker.listingClicks.set(listing, window.poeAutoClicker.maxClicksPerListing);
                                continue;
                            }
                        }

                        addListingClick(listing);
                        window.poeAutoClicker.lastClickTime = now;
                        window.poeAutoClicker.paused = true;

                        button.click();

                        window.poeAutoClicker.clickCount++;
                        console.log(`[${searchId}] Clicked item #${window.poeAutoClicker.clickCount}`);

                        window.poeAutoClicker.isClicking = false;
                        return true;
                    }

                    window.poeAutoClicker.isClicking = false;
                    return false;
                } catch (err) {
                    window.poeAutoClicker.isClicking = false;
                    return false;
                }
            }

            const observer = new MutationObserver((mutations) => {
                for (let i = 0; i < mutations.length; i++) {
                    if (mutations[i].addedNodes.length > 0) {
                        clickTopTravelButton();
                        return;
                    }
                }
            });

            const resultsContainer = document.querySelector('.results');
            if (resultsContainer) {
                observer.observe(resultsContainer, { childList: true, subtree: true });
                window.poeAutoClicker.observer = observer;
            }

            const intervalId = setInterval(() => {
                if (!window.poeAutoClicker.running) {
                    clearInterval(intervalId);
                    return;
                }
                clickTopTravelButton();
            }, 50);

            clickTopTravelButton();
            }, CHECK_INTERVAL, searchId, cooldownMs);
            
            console.log(`  ${searchId} - monitoring enabled`);
        }
        
        console.log('\nAll tabs are being monitored!\n');
        console.log('Auto-detecting new tabs every 30 seconds...\n');

        let waitingForResume = false;

        // Auto-detect new tabs every 30 seconds
        setInterval(async () => {
            try {
                const allPages = await browser.pages();
                const newTradePages = [];
                
                // Find all live search pages
                for (const p of allPages) {
                    const url = p.url();
                    if (url.includes('pathofexile.com/trade') && url.includes('/live')) {
                        if (!tabLabels.has(p)) {
                            newTradePages.push(p);
                        }
                    }
                }
                
                // If new tabs found, inject monitoring into them
                if (newTradePages.length > 0) {
                    console.log(`\nDetected ${newTradePages.length} new tab(s)!`);
                    
                    for (const page of newTradePages) {
                        const searchId = getSearchId(page.url());
                        tradePages.push(page);
                        tabLabels.set(page, searchId);
                        
                        console.log(`   Adding: ${searchId}`);
                        
                        await page.evaluate((checkInterval, searchId, cdMs) => {
                            if (window.poeAutoClicker && window.poeAutoClicker.running) {
                                return;
                            }

                            window.poeAutoClicker = {
                                running: true,
                                paused: false,
                                clickCount: 0,
                                observer: null,
                                lastClickTime: 0,
                                cooldownMs: cdMs,
                                isClicking: false,
                                searchId: searchId,
                                maxClicksPerListing: 3,
                                listingClicks: new WeakMap()
                            };

                            function getListingClicks(listing) {
                                return listing ? (window.poeAutoClicker.listingClicks.get(listing) || 0) : 0;
                            }

                            function addListingClick(listing) {
                                if (!listing) return 0;
                                const count = getListingClicks(listing) + 1;
                                window.poeAutoClicker.listingClicks.set(listing, count);
                                return count;
                            }

                            function isListingMaxed(listing) {
                                return listing && getListingClicks(listing) >= window.poeAutoClicker.maxClicksPerListing;
                            }

                            function clickTeleportAnyway() {
                                const buttons = document.querySelectorAll('.results button');
                                for (let i = 0; i < buttons.length; i++) {
                                    const text = buttons[i].textContent;
                                    if (text.indexOf('eleport') === -1 || text.indexOf('anyway') === -1) {
                                        continue;
                                    }
                                    const listing = buttons[i].closest('.resultset');
                                    if (isListingMaxed(listing)) {
                                        continue;
                                    }
                                    buttons[i].click();
                                    const count = addListingClick(listing);
                                    console.log(`[${searchId}] Clicked "Teleport anyway" (${count}/${window.poeAutoClicker.maxClicksPerListing})`);
                                    return true;
                                }
                                return false;
                            }

                            function clickTopTravelButton() {
                                if (window.poeAutoClicker.isClicking) {
                                    return false;
                                }

                                if (clickTeleportAnyway()) {
                                    return true;
                                }

                                if (window.poeAutoClicker.paused) {
                                    return false;
                                }

                                const now = Date.now();
                                if (now - window.poeAutoClicker.lastClickTime < window.poeAutoClicker.cooldownMs) {
                                    return false;
                                }

                                window.poeAutoClicker.isClicking = true;

                                try {
                                    const buttons = document.querySelectorAll('.results button');

                                    for (let i = 0; i < buttons.length; i++) {
                                        const button = buttons[i];
                                        const listing = button.closest('.resultset');

                                        if (isListingMaxed(listing)) {
                                            continue;
                                        }

                                        const text = button.textContent;

                                        if (text.indexOf('ravel') === -1) {
                                            continue;
                                        }

                                        const lower = text.toLowerCase();
                                        if (!(lower.includes('travel') && lower.includes('hideout'))) {
                                            continue;
                                        }

                                        if (button.disabled) {
                                            if (listing) addListingClick(listing);
                                            continue;
                                        }

                                        if (listing) {
                                            const lt = listing.textContent;
                                            if (lt.includes('no longer available') ||
                                                lt.includes('is outdated')) {
                                                if (listing) window.poeAutoClicker.listingClicks.set(listing, window.poeAutoClicker.maxClicksPerListing);
                                                continue;
                                            }
                                        }

                                        addListingClick(listing);
                                        window.poeAutoClicker.lastClickTime = now;
                                        window.poeAutoClicker.paused = true;

                                        button.click();

                                        window.poeAutoClicker.clickCount++;
                                        console.log(`[${searchId}] Clicked item #${window.poeAutoClicker.clickCount}`);

                                        window.poeAutoClicker.isClicking = false;
                                        return true;
                                    }

                                    window.poeAutoClicker.isClicking = false;
                                    return false;
                                } catch (err) {
                                    window.poeAutoClicker.isClicking = false;
                                    return false;
                                }
                            }

                            const observer = new MutationObserver((mutations) => {
                                for (let i = 0; i < mutations.length; i++) {
                                    if (mutations[i].addedNodes.length > 0) {
                                        clickTopTravelButton();
                                        return;
                                    }
                                }
                            });

                            const resultsContainer = document.querySelector('.results');
                            if (resultsContainer) {
                                observer.observe(resultsContainer, { childList: true, subtree: true });
                                window.poeAutoClicker.observer = observer;
                            }

                            const intervalId = setInterval(() => {
                                if (!window.poeAutoClicker.running) {
                                    clearInterval(intervalId);
                                    return;
                                }
                                clickTopTravelButton();
                            }, 50);

                            clickTopTravelButton();
                        }, CHECK_INTERVAL, searchId, cooldownMs);
                        
                        console.log(`   ${searchId} - monitoring enabled`);
                    }
                    
                    console.log(`\nNow monitoring ${tradePages.length} total tab(s)\n`);
                }
            } catch (err) {
                // Ignore errors during tab detection
            }
        }, 30000); // Check every 30 seconds

        // Monitor clicks and pause state across ALL tabs
        setInterval(async () => {
            try {
                // Check all tabs for clicks and pause state
                let anyPaused = false;
                let totalClicks = 0;
                let pausedSearchId = '';
                const closedPages = [];
                
                for (let i = 0; i < tradePages.length; i++) {
                    const page = tradePages[i];
                    
                    if (page.isClosed()) {
                        closedPages.push(i);
                        continue;
                    }
                    
                    try {
                        const status = await page.evaluate(() => ({
                            clickCount: window.poeAutoClicker?.clickCount || 0,
                            isPaused: window.poeAutoClicker?.paused || false,
                            searchId: window.poeAutoClicker?.searchId || ''
                        }));
                        
                        totalClicks += status.clickCount;
                        
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
                        tabLabels.delete(tradePages[index]);
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
                        console.log('  -> OR wait 60 seconds for auto-resume');
                    }
                    console.log('='.repeat(60) + '\n');
                    
                    const getAutoResume = () => state.autoResumeEnabled;
                    if (state.autoResumeEnabled) {
                        await waitForEnterOrTimeout(60000, getAutoResume);
                    } else {
                        await waitForEnter(getAutoResume);
                    }
                    
                    for (const page of tradePages) {
                        try {
                            if (!page.isClosed()) {
                                await page.evaluate(() => {
                                    if (window.poeAutoClicker) {
                                        window.poeAutoClicker.paused = false;
                                        window.poeAutoClicker.isClicking = false;
                                    }
                                });
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
                    console.log(`📊 Status: Monitoring ${tradePages.length} tabs | Clicks: ${clickCount} | ${new Date().toLocaleTimeString()}`);
                    lastNotification = Date.now();
                }
            } catch (err) {
                console.log('⚠️  Lost connection to page');
            }
        }, 500);

        // Cleanup on exit
        process.on('SIGINT', async () => {
            console.log('\n\n🛑 Stopping automation...');
            console.log(`📊 Final Stats: ${clickCount} travel to hideout buttons clicked across ${tradePages.length} tabs`);
            
            // Stop monitoring on ALL tabs (if browser still connected)
            if (browser && !browser._connection._closed) {
                for (const page of tradePages) {
                    try {
                        if (!page.isClosed()) {
                            await page.evaluate(() => {
                                if (window.poeAutoClicker) {
                                    window.poeAutoClicker.running = false;
                                    if (window.poeAutoClicker.observer) {
                                        window.poeAutoClicker.observer.disconnect();
                                    }
                                }
                            });
                        }
                    } catch (err) {
                        // Ignore errors on cleanup
                    }
                }
                
                try {
                    browser.disconnect();
                    console.log('✅ Disconnected (browser stays open)');
                } catch (err) {
                    // Browser already disconnected
                    console.log('✅ Browser already disconnected');
                }
            }
            
            process.exit(0);
        });

    } catch (err) {
        console.error('❌ Error during monitoring:', err.message);
        console.log('⚠️  Monitoring stopped. Script will continue running.');
        console.log('    Waiting for browser reconnect...\n');
    }
}

function waitForEnter(getAutoResume) {
    const HEARTBEAT_INTERVAL = 5000;

    return new Promise((resolve) => {
        let heartbeatTimer = null;
        let elapsed = 0;
        let dataListener;

        function cleanup() {
            if (heartbeatTimer) clearInterval(heartbeatTimer);
            if (dataListener) process.stdin.removeListener('data', dataListener);
        }

        dataListener = (data) => {
            const msg = data.toString().trim();
            if (msg.startsWith('__auto_resume__:')) return;
            cleanup();
            console.log('Enter pressed - resuming...');
            resolve('enter');
        };
        process.stdin.on('data', dataListener);

        heartbeatTimer = setInterval(() => {
            elapsed += HEARTBEAT_INTERVAL;

            // If auto-resume was toggled on while waiting, switch to timed mode
            if (getAutoResume && getAutoResume()) {
                cleanup();
                console.log('Auto-resume enabled mid-pause, switching to timed wait...');
                waitForEnterOrTimeout(60000, getAutoResume).then(resolve);
                return;
            }

            const waitSec = Math.floor(elapsed / 1000);
            console.log(`PAUSED - waiting for manual resume... (${waitSec}s elapsed)`);
        }, HEARTBEAT_INTERVAL);
    });
}

function waitForEnterOrTimeout(timeoutMs, getAutoResume) {
    const AUTO_RESUME_DELAY = timeoutMs;
    const HEARTBEAT_INTERVAL = 5000;

    return new Promise((resolve) => {
        let heartbeatTimer = null;
        let activeElapsed = 0;
        let dataListener;

        function cleanup() {
            if (heartbeatTimer) clearInterval(heartbeatTimer);
            if (dataListener) process.stdin.removeListener('data', dataListener);
        }

        dataListener = (data) => {
            const msg = data.toString().trim();
            if (msg.startsWith('__auto_resume__:')) return;
            cleanup();
            console.log('Enter pressed - resuming...');
            resolve('enter');
        };
        process.stdin.on('data', dataListener);

        heartbeatTimer = setInterval(() => {
            if (getAutoResume()) {
                activeElapsed += HEARTBEAT_INTERVAL;
                const remaining = Math.max(0, Math.ceil((AUTO_RESUME_DELAY - activeElapsed) / 1000));

                if (activeElapsed >= AUTO_RESUME_DELAY) {
                    cleanup();
                    console.log('Auto-resume timer elapsed - resuming...');
                    resolve('timeout');
                } else {
                    console.log(`PAUSED - auto-resuming in ${remaining}s...`);
                }
            } else {
                console.log('PAUSED - auto-resume disabled, waiting for manual resume...');
            }
        }, HEARTBEAT_INTERVAL);
    });
}

main().catch((error) => {
    console.error('❌ Error:', error);
    process.exit(1);
});


