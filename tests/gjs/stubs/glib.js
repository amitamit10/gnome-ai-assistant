import RealGLib from 'gi://GLib';
export const log = {timers: new Map(), nextId: 1, removed: []};
export default {
  PRIORITY_DEFAULT: 0, SOURCE_REMOVE: false, SOURCE_CONTINUE: true,
  get_monotonic_time: () => log.clock ?? RealGLib.get_monotonic_time(),
  timeout_add: (prio, ms, cb) => { const id = log.nextId++; log.timers.set(id, {ms, cb}); return id; },
  source_remove: id => { log.removed.push(id); return log.timers.delete(id); },
};
