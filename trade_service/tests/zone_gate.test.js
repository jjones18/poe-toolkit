'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');

const {
  POE1_TOWN_AREA_IDS,
  POE2_TOWN_AREA_IDS,
  extractAreaId,
  classifyArea,
  readLatestArea,
  ZoneGate,
} = require('../zone_gate');

const POE1_ACT_TOWNS = [
  '1_1_town', '1_2_town', '1_3_town', '1_4_town', '1_5_town',
  '2_6_town', '2_7_town', '2_8_town', '2_9_town', '2_10_town',
];

test('PoE 1 explicitly allows all ten act towns and both Epilogue towns', () => {
  for (const areaId of POE1_ACT_TOWNS) {
    assert.equal(POE1_TOWN_AREA_IDS.has(areaId), true, areaId);
    assert.deepEqual(classifyArea('poe1', areaId), {
      safe: true,
      areaId,
      kind: 'town',
    });
  }
  for (const areaId of ['2_11_town', '2_11_endgame_town']) {
    assert.equal(POE1_TOWN_AREA_IDS.has(areaId), true, areaId);
    assert.equal(classifyArea('poe1', areaId).safe, true, areaId);
  }
});

test('PoE 1 treats the Deepwater league hub as a built-in safe town', () => {
  assert.equal(POE1_TOWN_AREA_IDS.has('DeepwaterHub'), true);
  assert.deepEqual(classifyArea('poe1', 'DeepwaterHub'), {
    safe: true,
    areaId: 'DeepwaterHub',
    kind: 'town',
  });
});

test('custom allowed zones are classified explicitly', () => {
  assert.equal(classifyArea('poe1', 'FutureLeagueHub').safe, false);
  assert.deepEqual(classifyArea('poe1', 'FutureLeagueHub', ['FutureLeagueHub']), {
    safe: true,
    areaId: 'FutureLeagueHub',
    kind: 'custom',
  });
  assert.equal(classifyArea('poe2', 'FutureLeagueHub').safe, false);
});

test('PoE 2 explicitly allows known campaign and endgame towns', () => {
  for (const areaId of ['G1_town', 'G2_town', 'G3_town', 'G4_town', 'G_Endgame_Town', 'P1_Town', 'P2_Town', 'P3_Town']) {
    assert.equal(POE2_TOWN_AREA_IDS.has(areaId), true, areaId);
    assert.equal(classifyArea('poe2', areaId).safe, true, areaId);
  }
});

test('anchored Hideout IDs are safe but hideout unlock maps and town substrings are blocked', () => {
  assert.equal(classifyArea('poe1', 'HideoutBeach').safe, true);
  assert.equal(classifyArea('poe2', 'HideoutLimestone').safe, true);
  assert.equal(classifyArea('poe2', 'MapHideoutLimestone_Claimable').safe, false);
  assert.equal(classifyArea('poe1', 'MapWorldsCrimsonTownship').safe, false);
  assert.equal(classifyArea('poe1', 'AfflictionTown10').safe, false);
});

test('unknown or malformed areas fail closed', () => {
  assert.deepEqual(classifyArea('poe1', ''), {
    safe: false,
    areaId: '',
    kind: 'unknown',
  });
  assert.equal(classifyArea('poe1', 'MapWorldsCemetery').safe, false);
  assert.equal(classifyArea('poe2', 'G1_4').safe, false);
});

test('extractAreaId parses PoE generating-level log lines only', () => {
  assert.equal(
    extractAreaId('2026/05/29 [DEBUG Client 312] Generating level 15 area "G1_town" with seed 1'),
    'G1_town',
  );
  assert.equal(extractAreaId('[SCENE] Set Source [Clearfell Encampment]'), null);
});

test('startup detection reads the latest area from the tail without scanning the whole file', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'poe-zone-gate-'));
  const logPath = path.join(dir, 'Client.txt');
  try {
    fs.writeFileSync(logPath, `${'x'.repeat(1_200_000)}\n`);
    fs.appendFileSync(logPath, '[DEBUG Client] Generating level 82 area "MapWorldsCemetery" with seed 123\n');
    fs.appendFileSync(logPath, '[DEBUG Client] Generating level 65 area "HideoutBeach" with seed 1\n');

    assert.deepEqual(readLatestArea(logPath, 'poe1'), {
      safe: true,
      areaId: 'HideoutBeach',
      kind: 'hideout',
    });
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('missing log fails closed with an actionable state', () => {
  const result = readLatestArea('/definitely/missing/Client.txt', 'poe1');
  assert.equal(result.safe, false);
  assert.equal(result.kind, 'missing-log');
});

test('watcher blocks in a map and enables only after a safe zone transition', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'poe-zone-watch-'));
  const logPath = path.join(dir, 'Client.txt');
  fs.writeFileSync(logPath, '[DEBUG Client] Generating level 82 area "MapWorldsCemetery" with seed 1\n');
  const gate = new ZoneGate({
    enabled: true,
    logPath,
    gameId: 'poe1',
    pollIntervalMs: 5,
  });

  try {
    assert.deepEqual(gate.start(), {
      safe: false,
      areaId: 'MapWorldsCemetery',
      kind: 'unsafe-area',
    });

    const changed = new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('zone transition timed out')), 1_000);
      gate.once('change', state => {
        clearTimeout(timeout);
        resolve(state);
      });
    });
    fs.appendFileSync(logPath, '[DEBUG Client] Generating level 60 area "HideoutBeach" with seed 2\n');

    assert.deepEqual(await changed, {
      safe: true,
      areaId: 'HideoutBeach',
      kind: 'hideout',
    });
  } finally {
    gate.stop();
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('allowArea immediately reclassifies the current exact area ID', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'poe-zone-allow-'));
  const logPath = path.join(dir, 'Client.txt');
  fs.writeFileSync(logPath, '[DEBUG Client] Generating level 80 area "FutureLeagueHub" with seed 1\n');
  const gate = new ZoneGate({ enabled: true, logPath, gameId: 'poe1' });

  try {
    assert.equal(gate.start().safe, false);
    assert.equal(gate.allowArea('FutureLeagueHub'), true);
    assert.deepEqual(gate.getState(), {
      safe: true,
      areaId: 'FutureLeagueHub',
      kind: 'custom',
    });
    assert.equal(gate.allowArea('FutureLeagueHub'), false);
    assert.equal(gate.allowArea('bad-zone;control'), false);
  } finally {
    gate.stop();
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('removeArea immediately blocks a current custom area again', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'poe-zone-gate-remove-'));
  const logPath = path.join(dir, 'Client.txt');
  fs.writeFileSync(
    logPath,
    '[DEBUG Client] Generating level 1 area "FutureLeagueHub" with seed 1\n',
  );
  const gate = new ZoneGate({
    enabled: true,
    logPath,
    gameId: 'poe1',
    allowedAreaIds: ['FutureLeagueHub'],
  });

  try {
    assert.equal(gate.start().safe, true);
    assert.equal(gate.removeArea('FutureLeagueHub'), true);
    assert.deepEqual(gate.getState(), {
      safe: false,
      areaId: 'FutureLeagueHub',
      kind: 'unsafe-area',
    });
    assert.equal(gate.removeArea('FutureLeagueHub'), false);
    assert.equal(gate.removeArea('DeepwaterHub'), false);
  } finally {
    gate.stop();
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
