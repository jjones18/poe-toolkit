'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const { isLiveTradeUrl } = require('../trade_monitor');

test('live trade URL accepts canonical and subdomain hosts', () => {
    assert.equal(isLiveTradeUrl('https://www.pathofexile.com/trade/search/Ancestor/abc/live', '/trade'), true);
    assert.equal(isLiveTradeUrl('https://pathofexile.com/trade/search/Ancestor/abc/live', '/trade'), true);
    assert.equal(isLiveTradeUrl('https://nl.pathofexile.com/trade/search/Ancestor/abc/live', '/trade'), true);
    // PoE 2 path
    assert.equal(isLiveTradeUrl('https://www.pathofexile.com/trade2/search/poe2/abc/live', '/trade2'), true);
});

test('live trade URL rejects impostor hosts', () => {
    assert.equal(isLiveTradeUrl('https://evilpathofexile.com/trade/search/Ancestor/abc/live', '/trade'), false);
    assert.equal(isLiveTradeUrl('https://notpathofexile.com/trade/search/Ancestor/abc/live', '/trade'), false);
    assert.equal(isLiveTradeUrl('https://pathofexile.com.evil.io/trade/search/Ancestor/abc/live', '/trade'), false);
    assert.equal(isLiveTradeUrl('https://www.pathofexile.com.example.net/trade/search/Ancestor/abc/live', '/trade'), false);
});

test('live trade URL rejects wrong paths', () => {
    assert.equal(isLiveTradeUrl('https://www.pathofexile.com/other/search/Ancestor/abc/live', '/trade'), false);
    // PoE 1 monitor must not accept a PoE 2 live search
    assert.equal(isLiveTradeUrl('https://www.pathofexile.com/trade2/search/poe2/abc/live', '/trade'), false);
});

test('live trade URL rejects malformed URLs', () => {
    assert.equal(isLiveTradeUrl('not a url', '/trade'), false);
    assert.equal(isLiveTradeUrl('', '/trade'), false);
});
