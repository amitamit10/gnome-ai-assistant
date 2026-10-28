export const calls = {dbus: [], cancelled: 0, failNext: null};
class Cancellable { cancel() { calls.cancelled++; } }
const session = {
  call(name, path, iface, method, params, replyType, flags, timeout, cancellable, cb) {
    calls.dbus.push({name, path, iface, method});
    const err = calls.failNext; calls.failNext = null;
    if (cb) cb({call_finish: () => { if (err) throw err; return {}; }}, {});
  },
};
export default {Cancellable, DBus: {session}, DBusCallFlags: {NONE: 0}, IOErrorEnum: {CANCELLED: 19}};
