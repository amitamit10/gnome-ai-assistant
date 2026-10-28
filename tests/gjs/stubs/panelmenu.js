export class Button {
  constructor() { this.handlers = {}; this.children = []; this.destroyed = false; }
  add_child(c) { this.children.push(c); }
  connect(sig, cb) { this.handlers[sig] = cb; return 1; }
  destroy() { this.destroyed = true; }
}
