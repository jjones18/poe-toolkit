'use strict';

const fs = require('fs');
const { EventEmitter } = require('events');

const DEFAULT_TAIL_BYTES = 1024 * 1024;
const DEFAULT_POLL_INTERVAL_MS = 250;

const POE1_TOWN_AREA_IDS = new Set([
  '1_1_town',
  '1_2_town',
  '1_3_town',
  '1_4_town',
  '1_5_town',
  '2_6_town',
  '2_7_town',
  '2_8_town',
  '2_9_town',
  '2_10_town',
  '2_11_town',
  '2_11_endgame_town',
  'DeepwaterHub',
]);

const POE2_TOWN_AREA_IDS = new Set([
  'G1_town',
  'G2_town',
  'G3_town',
  'G4_town',
  'G_Endgame_Town',
  'P1_Town',
  'P2_Town',
  'P3_Town',
  'C_G1_town',
  'C_G2_town',
  'C_G3_town',
]);

function extractAreaId(line) {
  const match = /Generating level \d+ area "([^"]+)"/.exec(line);
  return match ? match[1] : null;
}

function isValidAreaId(areaId) {
  return typeof areaId === 'string' && /^[A-Za-z0-9_]+$/.test(areaId);
}

function normalizeAllowedAreaIds(areaIds) {
  if (!areaIds || typeof areaIds[Symbol.iterator] !== 'function') return new Set();
  return new Set([...areaIds].filter(isValidAreaId));
}

function classifyArea(gameId, areaId, allowedAreaIds = []) {
  const normalizedAreaId = typeof areaId === 'string' ? areaId : '';
  if (!normalizedAreaId) {
    return { safe: false, areaId: '', kind: 'unknown' };
  }

  // Real hideout instances use an anchored Hideout... ID. Unlock maps use
  // MapHideout... and therefore intentionally fail this check.
  if (/^Hideout[A-Za-z0-9_]*$/.test(normalizedAreaId)) {
    return { safe: true, areaId: normalizedAreaId, kind: 'hideout' };
  }

  const towns = gameId === 'poe2' ? POE2_TOWN_AREA_IDS : POE1_TOWN_AREA_IDS;
  if (towns.has(normalizedAreaId)) {
    return { safe: true, areaId: normalizedAreaId, kind: 'town' };
  }

  if (normalizeAllowedAreaIds(allowedAreaIds).has(normalizedAreaId)) {
    return { safe: true, areaId: normalizedAreaId, kind: 'custom' };
  }

  return { safe: false, areaId: normalizedAreaId, kind: 'unsafe-area' };
}

function readTail(logPath, maxBytes = DEFAULT_TAIL_BYTES) {
  const stat = fs.statSync(logPath);
  const length = Math.min(stat.size, maxBytes);
  const start = stat.size - length;
  const buffer = Buffer.alloc(length);
  const fd = fs.openSync(logPath, 'r');
  try {
    if (length > 0) fs.readSync(fd, buffer, 0, length, start);
  } finally {
    fs.closeSync(fd);
  }
  return { text: buffer.toString('utf8'), stat };
}

function latestAreaIdFromText(text) {
  let latest = null;
  for (const line of text.split(/\r?\n/)) {
    const areaId = extractAreaId(line);
    if (areaId) latest = areaId;
  }
  return latest;
}

function readLatestArea(logPath, gameId, maxBytes = DEFAULT_TAIL_BYTES, allowedAreaIds = []) {
  try {
    const { text } = readTail(logPath, maxBytes);
    return classifyArea(gameId, latestAreaIdFromText(text), allowedAreaIds);
  } catch (error) {
    return {
      safe: false,
      areaId: '',
      kind: error && error.code === 'ENOENT' ? 'missing-log' : 'log-error',
      detail: error.message,
    };
  }
}

class ZoneGate extends EventEmitter {
  constructor({
    enabled = true,
    logPath = '',
    gameId = 'poe1',
    allowedAreaIds = [],
    pollIntervalMs = DEFAULT_POLL_INTERVAL_MS,
  } = {}) {
    super();
    this.enabled = Boolean(enabled);
    this.logPath = logPath;
    this.gameId = gameId === 'poe2' ? 'poe2' : 'poe1';
    this.allowedAreaIds = normalizeAllowedAreaIds(allowedAreaIds);
    this.pollIntervalMs = pollIntervalMs;
    this.state = this.enabled
      ? { safe: false, areaId: '', kind: logPath ? 'unknown' : 'missing-log' }
      : { safe: true, areaId: '', kind: 'disabled' };
    this.offset = 0;
    this.inode = null;
    this.partial = '';
    this.timer = null;
  }

  getState() {
    return { ...this.state };
  }

  allowArea(areaId) {
    if (!isValidAreaId(areaId) || classifyArea(this.gameId, areaId).safe) return false;
    const sizeBefore = this.allowedAreaIds.size;
    this.allowedAreaIds.add(areaId);
    if (this.allowedAreaIds.size === sizeBefore) return false;
    if (this.state.areaId === areaId) {
      this._setState(classifyArea(this.gameId, areaId, this.allowedAreaIds));
    }
    return true;
  }

  _setState(next) {
    const previous = this.state;
    this.state = next;
    if (
      previous.safe !== next.safe ||
      previous.areaId !== next.areaId ||
      previous.kind !== next.kind
    ) {
      this.emit('change', this.getState());
    }
  }

  _initializeFromTail() {
    if (!this.enabled) return;
    if (!this.logPath) {
      this._setState({ safe: false, areaId: '', kind: 'missing-log' });
      return;
    }

    try {
      const { text, stat } = readTail(this.logPath);
      const areaId = latestAreaIdFromText(text);
      this.offset = stat.size;
      this.inode = stat.ino;
      this.partial = '';
      this._setState(classifyArea(this.gameId, areaId, this.allowedAreaIds));
    } catch (error) {
      this.offset = 0;
      this.inode = null;
      this.partial = '';
      this._setState({
        safe: false,
        areaId: '',
        kind: error && error.code === 'ENOENT' ? 'missing-log' : 'log-error',
        detail: error.message,
      });
    }
  }

  _consume(text) {
    const combined = this.partial + text;
    const lines = combined.split(/\r?\n/);
    this.partial = lines.pop() || '';
    for (const line of lines) {
      const areaId = extractAreaId(line);
      if (areaId) {
        this._setState(classifyArea(this.gameId, areaId, this.allowedAreaIds));
      }
    }
  }

  _poll() {
    if (!this.enabled || !this.logPath) return;
    try {
      const stat = fs.statSync(this.logPath);
      if (this.inode !== stat.ino || stat.size < this.offset) {
        this._initializeFromTail();
        return;
      }
      if (stat.size === this.offset) return;

      const length = stat.size - this.offset;
      const buffer = Buffer.alloc(length);
      const fd = fs.openSync(this.logPath, 'r');
      try {
        fs.readSync(fd, buffer, 0, length, this.offset);
      } finally {
        fs.closeSync(fd);
      }
      this.offset = stat.size;
      this._consume(buffer.toString('utf8'));
    } catch (error) {
      this._setState({
        safe: false,
        areaId: '',
        kind: error && error.code === 'ENOENT' ? 'missing-log' : 'log-error',
        detail: error.message,
      });
    }
  }

  start() {
    if (this.timer || !this.enabled) return this.getState();
    this._initializeFromTail();
    this.timer = setInterval(() => this._poll(), this.pollIntervalMs);
    if (typeof this.timer.unref === 'function') this.timer.unref();
    return this.getState();
  }

  stop() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }
}

module.exports = {
  POE1_TOWN_AREA_IDS,
  POE2_TOWN_AREA_IDS,
  extractAreaId,
  isValidAreaId,
  classifyArea,
  readLatestArea,
  ZoneGate,
};
