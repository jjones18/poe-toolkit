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

async function main() {
    // Check for command line arguments
    const args = process.argv.slice(2);
    const autoResumeEnabled = args.includes('--auto-resume');
    
    console.log('🎮 PoE Trade Auto - Connect to Existing Browser\n');
    console.log('Attempting to connect to your Brave browser on port 9222...\n');

    let browser = await connectToBrowser();
    
    if (!browser) {
        console.log('❌ Could not connect to browser!');
        console.log('Make sure you started Brave with remote debugging.');
        console.log('\nRun: start_brave_debugging.bat\n');
        process.exit(1);
    }

    console.log('✅ Connected to your Brave browser!\n');

    if (autoResumeEnabled) {
        console.log('✅ Auto-resume enabled - Will resume after 60s\n');
    } else {
        console.log('✅ Manual resume only - Press Enter to continue\n');
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
                
                // Restart the monitoring process with same auto-resume setting
                await startMonitoring(browser, autoResumeEnabled);
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
                    await startMonitoring(browser, autoResumeEnabled);
                }
            }, 5000);
        }
    });

    // Start monitoring with auto-resume setting
    await startMonitoring(browser, autoResumeEnabled);
}


async function startMonitoring(browser, autoResumeEnabled) {
    try {
        const pages = await browser.pages();
        
        if (pages.length === 0) {
            console.log('❌ No pages found. Please open a tab in Brave first.');
            process.exit(1);
        }

        // Find ALL PoE trade live search pages
        const tradePages = [];
        for (const p of pages) {
            const url = p.url();
            if (url.includes('pathofexile.com/trade') && url.includes('/live')) {
                tradePages.push(p);
            }
        }

        if (tradePages.length === 0) {
            console.log('❌ No PoE trade live search pages found!');
            console.log('Please open at least one live search tab.');
            process.exit(1);
        }

        console.log(`\n✅ Found ${tradePages.length} live search tab(s)!\n`);
        for (let i = 0; i < tradePages.length; i++) {
            const url = tradePages[i].url();
            const searchName = url.match(/trade\/search\/[^/]+\/([^/]+)/)?.[1] || 'unknown';
            console.log(`   ${i + 1}. ${searchName}`);
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
        let isPausedGlobal = false;

        console.log('👀 Monitoring ALL tabs for new listings...');
        console.log(`🔍 Watching ${tradePages.length} live search(es) simultaneously`);
        console.log('🏠 Will click FIRST item that appears in ANY tab');
        console.log('⏸️  Will PAUSE after each click (press Enter to resume)');
        console.log('⏹️  Press Ctrl+C to stop completely\n');

        // Inject monitoring script into ALL tabs
        for (let i = 0; i < tradePages.length; i++) {
            const page = tradePages[i];
            const tabIndex = i;
            
            await page.evaluate((checkInterval, tabIndex) => {
            // Don't re-inject if already running
            if (window.poeAutoClicker && window.poeAutoClicker.running) {
                console.log('⚠️  Already running! Stopping old instance...');
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
                cooldownMs: 5000, // 5 second cooldown between clicks
                isClicking: false, // Lock to prevent multiple simultaneous clicks
                tabIndex: tabIndex // Which tab this is
            };

            function clickTopTravelButton() {
                // Prevent multiple simultaneous clicks
                if (window.poeAutoClicker.isClicking) {
                    return false;
                }

                // Only click if not paused
                if (window.poeAutoClicker.paused) {
                    return false;
                }

                // Check cooldown - prevent rate limiting
                const now = Date.now();
                const timeSinceLastClick = now - window.poeAutoClicker.lastClickTime;
                if (timeSinceLastClick < window.poeAutoClicker.cooldownMs) {
                    // Still in cooldown
                    return false;
                }

                // Set lock
                window.poeAutoClicker.isClicking = true;

                try {
                    // Find ALL travel to hideout buttons
                    const allButtons = Array.from(document.querySelectorAll('button'));
                    const travelButtons = allButtons.filter(button => {
                        const buttonText = button.textContent.trim().toLowerCase();
                        return buttonText.includes('travel') && buttonText.includes('hideout');
                    });

                    if (travelButtons.length === 0) {
                        window.poeAutoClicker.isClicking = false;
                        return false;
                    }

                    // Get the FIRST (top) button that hasn't been clicked
                    for (const button of travelButtons) {
                        // Skip if already clicked
                        if (button.classList.contains('poe-auto-clicked')) {
                            continue;
                        }

                        // Check if item is still available (not sold/outdated)
                        const listingElement = button.closest('.resultset');
                        if (listingElement) {
                            const listingText = listingElement.textContent.toLowerCase();
                            
                            // Skip if item is no longer available or outdated
                            if (listingText.includes('no longer available') || 
                                listingText.includes('is outdated') ||
                                listingText.includes('item is in demand')) {
                                
                                // Mark as clicked so we don't check it again
                                button.classList.add('poe-auto-clicked');
                                console.log('⏭️  Skipping unavailable/outdated item');
                                continue; // Keep looking for next valid item
                            }
                            
                            // Check if button is disabled
                            if (button.disabled || button.hasAttribute('disabled')) {
                                button.classList.add('poe-auto-clicked');
                                console.log('⏭️  Skipping disabled button');
                                continue;
                            }
                        }

                        // This is a valid item! Click it
                        button.classList.add('poe-auto-clicked');
                        window.poeAutoClicker.lastClickTime = now;
                        window.poeAutoClicker.paused = true; // Pause BEFORE clicking
                        
                        button.click();
                        
                        window.poeAutoClicker.clickCount++;
                        console.log(`🏠 [Tab ${tabIndex + 1}] Clicked TOP available item! Total: ${window.poeAutoClicker.clickCount}`);
                        console.log('⏸️  PAUSED - Waiting for resume signal...');
                        
                        window.poeAutoClicker.isClicking = false;
                        return true;
                    }
                    
                    // No valid buttons found
                    window.poeAutoClicker.isClicking = false;
                    return false;
                } catch (err) {
                    window.poeAutoClicker.isClicking = false;
                    console.error('Error clicking button:', err);
                    return false;
                }
            }

            const intervalId = setInterval(() => {
                if (!window.poeAutoClicker.running) {
                    clearInterval(intervalId);
                    return;
                }
                clickTopTravelButton();
            }, checkInterval);

            const observer = new MutationObserver(() => {
                clickTopTravelButton();
            });

            const resultsContainer = document.querySelector('.results');
            if (resultsContainer) {
                observer.observe(resultsContainer, { childList: true, subtree: true });
                window.poeAutoClicker.observer = observer;
                console.log('✅ Observer attached to results container');
            } else {
                console.log('⚠️  Could not find results container. Will use interval only.');
            }

            clickTopTravelButton();
            }, CHECK_INTERVAL, tabIndex);
            
            console.log(`✅ Tab ${i + 1} monitoring enabled`);
        }
        
        console.log('\n✅ All tabs are being monitored!\n');
        console.log('🔄 Auto-detecting new tabs every 30 seconds...\n');

        let isPaused = false;
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
                        // Check if this page is already being monitored
                        const alreadyMonitored = tradePages.some(existingPage => existingPage.url() === url);
                        if (!alreadyMonitored) {
                            newTradePages.push(p);
                        }
                    }
                }
                
                // If new tabs found, inject monitoring into them
                if (newTradePages.length > 0) {
                    console.log(`\n✨ Detected ${newTradePages.length} new tab(s)!`);
                    
                    for (const page of newTradePages) {
                        const tabIndex = tradePages.length;
                        tradePages.push(page); // Add to monitored list
                        
                        const url = page.url();
                        const searchName = url.match(/trade\/search\/[^/]+\/([^/]+)/)?.[1] || 'unknown';
                        console.log(`   Adding: ${searchName}`);
                        
                        // Inject monitoring script into new tab
                        await page.evaluate((checkInterval, tabIndex) => {
                            if (window.poeAutoClicker && window.poeAutoClicker.running) {
                                return; // Already running
                            }

                            window.poeAutoClicker = {
                                running: true,
                                paused: false,
                                clickCount: 0,
                                observer: null,
                                lastClickTime: 0,
                                cooldownMs: 5000,
                                isClicking: false,
                                tabIndex: tabIndex
                            };

                            function clickTopTravelButton() {
                                if (window.poeAutoClicker.isClicking) {
                                    return false;
                                }
                                if (window.poeAutoClicker.paused) {
                                    return false;
                                }

                                const now = Date.now();
                                const timeSinceLastClick = now - window.poeAutoClicker.lastClickTime;
                                if (timeSinceLastClick < window.poeAutoClicker.cooldownMs) {
                                    return false;
                                }

                                window.poeAutoClicker.isClicking = true;

                                try {
                                    const allButtons = Array.from(document.querySelectorAll('button'));
                                    const travelButtons = allButtons.filter(button => {
                                        const buttonText = button.textContent.trim().toLowerCase();
                                        return buttonText.includes('travel') && buttonText.includes('hideout');
                                    });

                                    if (travelButtons.length === 0) {
                                        window.poeAutoClicker.isClicking = false;
                                        return false;
                                    }

                                    for (const button of travelButtons) {
                                        if (button.classList.contains('poe-auto-clicked')) {
                                            continue;
                                        }

                                        const listingElement = button.closest('.resultset');
                                        if (listingElement) {
                                            const listingText = listingElement.textContent.toLowerCase();
                                            
                                            if (listingText.includes('no longer available') || 
                                                listingText.includes('is outdated') ||
                                                listingText.includes('item is in demand')) {
                                                button.classList.add('poe-auto-clicked');
                                                console.log('⏭️  Skipping unavailable/outdated item');
                                                continue;
                                            }
                                            
                                            if (button.disabled || button.hasAttribute('disabled')) {
                                                button.classList.add('poe-auto-clicked');
                                                console.log('⏭️  Skipping disabled button');
                                                continue;
                                            }
                                        }

                                        button.classList.add('poe-auto-clicked');
                                        window.poeAutoClicker.lastClickTime = now;
                                        window.poeAutoClicker.paused = true;
                                        
                                        button.click();
                                        
                                        window.poeAutoClicker.clickCount++;
                                        console.log(`🏠 [Tab ${tabIndex + 1}] Clicked TOP available item! Total: ${window.poeAutoClicker.clickCount}`);
                                        console.log('⏸️  PAUSED - Waiting for resume signal...');
                                        
                                        window.poeAutoClicker.isClicking = false;
                                        return true;
                                    }
                                    
                                    window.poeAutoClicker.isClicking = false;
                                    return false;
                                } catch (err) {
                                    window.poeAutoClicker.isClicking = false;
                                    console.error('Error clicking button:', err);
                                    return false;
                                }
                            }

                            const intervalId = setInterval(() => {
                                if (!window.poeAutoClicker.running) {
                                    clearInterval(intervalId);
                                    return;
                                }
                                clickTopTravelButton();
                            }, checkInterval);

                            const observer = new MutationObserver(() => {
                                clickTopTravelButton();
                            });

                            const resultsContainer = document.querySelector('.results');
                            if (resultsContainer) {
                                observer.observe(resultsContainer, { childList: true, subtree: true });
                                window.poeAutoClicker.observer = observer;
                            }

                            clickTopTravelButton();
                        }, CHECK_INTERVAL, tabIndex);
                        
                        console.log(`   ✅ Tab ${tabIndex + 1} monitoring enabled`);
                    }
                    
                    console.log(`\n🔍 Now monitoring ${tradePages.length} total tab(s)\n`);
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
                let pausedTabIndex = -1;
                const closedPages = [];
                
                for (let i = 0; i < tradePages.length; i++) {
                    const page = tradePages[i];
                    
                    // Check if page is closed
                    if (page.isClosed()) {
                        closedPages.push(i);
                        continue;
                    }
                    
                    try {
                        const status = await page.evaluate(() => ({
                            clickCount: window.poeAutoClicker?.clickCount || 0,
                            isRunning: window.poeAutoClicker?.running || false,
                            isPaused: window.poeAutoClicker?.paused || false,
                            tabIndex: window.poeAutoClicker?.tabIndex || 0
                        }));
                        
                        totalClicks += status.clickCount;
                        
                        if (status.isPaused) {
                            anyPaused = true;
                            pausedTabIndex = i;
                        }
                    } catch (err) {
                        // Page might have been closed or navigated away
                        closedPages.push(i);
                    }
                }
                
                // Remove closed pages from the array (in reverse order to maintain indices)
                if (closedPages.length > 0) {
                    for (let i = closedPages.length - 1; i >= 0; i--) {
                        const index = closedPages[i];
                        tradePages.splice(index, 1);
                    }
                    console.log(`\n❌ Removed ${closedPages.length} closed tab(s)`);
                    console.log(`🔍 Now monitoring ${tradePages.length} tab(s)\n`);
                }

                // Check if just clicked (count increased)
                if (totalClicks > clickCount) {
                    const newClicks = totalClicks - clickCount;
                    console.log(`✨ Clicked ${newClicks} item(s)! Total clicks: ${totalClicks}`);
                    clickCount = totalClicks;
                }

                // Check if paused and need to prompt for resume
                if (anyPaused && !waitingForResume) {
                    waitingForResume = true;
                    console.log('\n' + '='.repeat(60));
                    console.log('⏸️  PAUSED');
                    console.log('='.repeat(60));
                    console.log(`  Clicked item in Tab ${pausedTabIndex + 1}!`);
                    console.log('  When you\'re ready for the next one:');
                    console.log('  → Press ENTER to resume monitoring ALL tabs');
                    if (autoResumeEnabled) {
                        console.log('  ⏱️  OR wait 60 seconds for auto-resume');
                    }
                    console.log('='.repeat(60) + '\n');
                    
                    // Wait for Enter key OR 60 second timeout (if enabled)
                    if (autoResumeEnabled) {
                        await waitForEnterOrTimeout(60000); // 60 seconds
                    } else {
                        await waitForEnter();
                    }
                    
                    // Resume ALL tabs
                    for (const page of tradePages) {
                        await page.evaluate(() => {
                            if (window.poeAutoClicker) {
                                window.poeAutoClicker.paused = false;
                                window.poeAutoClicker.isClicking = false; // Reset lock
                                console.log('▶️  RESUMED');
                            }
                        });
                    }
                    
                    console.log(`▶️  RESUMED - Monitoring all ${tradePages.length} tabs...\n`);
                    waitingForResume = false;
                    isPausedGlobal = false;
                }

                // Periodic status update (only when not paused)
                if (!anyPaused && Date.now() - lastNotification > 30000) {
                    console.log(`📊 Status: Monitoring ${tradePages.length} tabs | Clicks: ${clickCount} | ${new Date().toLocaleTimeString()}`);
                    lastNotification = Date.now();
                }
            } catch (err) {
                console.log('⚠️  Lost connection to page');
            }
        }, 100); // Fast polling for instant response

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

function waitForEnter() {
    return new Promise((resolve) => {
        process.stdin.once('data', () => resolve());
    });
}

function waitForEnterOrTimeout(timeoutMs) {
    return new Promise((resolve) => {
        let timeout;
        let dataListener;
        
        // Set up timeout
        timeout = setTimeout(() => {
            process.stdin.removeListener('data', dataListener);
            console.log('⏱️  60 seconds elapsed - auto-resuming...');
            resolve('timeout');
        }, timeoutMs);
        
        // Set up Enter key listener
        dataListener = () => {
            clearTimeout(timeout);
            console.log('⌨️  Enter pressed - resuming...');
            resolve('enter');
        };
        
        process.stdin.once('data', dataListener);
    });
}

main().catch((error) => {
    console.error('❌ Error:', error);
    process.exit(1);
});


