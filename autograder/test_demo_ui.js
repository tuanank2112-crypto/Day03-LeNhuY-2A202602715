"use strict";

/*
 * Browser-free smoke test for the static demo. It verifies the same click path
 * a viewer uses, including the HN → NY case that is outside the local dataset.
 */

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class ClassList {
  add() {}
  remove() {}
  toggle() {}
}

class Element {
  constructor() {
    this.children = [];
    this.classList = new ClassList();
    this.dataset = {};
    this.events = new Map();
    this.value = "";
    this.textContent = "";
    this.innerHTML = "";
    this.disabled = false;
  }

  addEventListener(type, callback) {
    this.events.set(type, callback);
  }

  append(...items) {
    this.children.push(...items);
  }

  replaceChildren(...items) {
    this.children = items;
  }
}

const elements = new Map(
  [
    "#query",
    "#max-iterations",
    "#iteration-value",
    "#run-demo",
    "#data-status",
    "#baseline-answer",
    "#agent-answer",
    "#agent-status",
    "#run-feedback",
    "#tool-count",
    "#iteration-count",
    "#trace-list",
    "#trace-summary",
    "#reset",
  ].map((selector) => [selector, new Element()]),
);
elements.get("#max-iterations").value = "5";

const presets = ["multi", "flight", "weather", "empty", "unsupported", "faq"].map(
  (name) => {
    const element = new Element();
    element.dataset.preset = name;
    return element;
  },
);

const document = {
  querySelector(selector) {
    return elements.get(selector) || null;
  },
  querySelectorAll(selector) {
    return selector === ".preset" ? presets : [];
  },
  createElement() {
    return new Element();
  },
  createTextNode(text) {
    const node = new Element();
    node.textContent = text;
    return node;
  },
};

const sandbox = {
  document,
  window: {},
  Intl,
  Number,
  RegExp,
  String,
  JSON,
  Set,
  Map,
  Math,
  console,
};

vm.createContext(sandbox);
vm.runInContext(
  fs.readFileSync(path.join(__dirname, "..", "docs", "app.js"), "utf8"),
  sandbox,
  { filename: "docs/app.js" },
);

function clickRun(query, iterations = "5") {
  elements.get("#query").value = query;
  elements.get("#max-iterations").value = iterations;
  elements.get("#run-demo").events.get("click")();
  return {
    answer: elements.get("#agent-answer").textContent,
    status: elements.get("#agent-status").textContent,
    tools: String(elements.get("#tool-count").textContent),
    iterations: String(elements.get("#iteration-count").textContent),
    feedback: elements.get("#run-feedback").textContent,
    disabled: elements.get("#run-demo").disabled,
  };
}

const combined = clickRun(
  "Tìm cho tôi chuyến bay từ HAN đi SGN dưới 2 triệu, rồi cho biết thời tiết SGN nên mặc gì?",
);
assert.equal(combined.status, "completed");
assert.equal(combined.tools, "2");
assert.equal(combined.iterations, "3");
assert.match(combined.answer, /VN213/);
assert.match(combined.answer, /32°C/);

const unsupported = clickRun("Tìm chuyến bay từ HN sang NY dưới 2 triệu.");
assert.equal(unsupported.status, "completed");
assert.equal(unsupported.tools, "1");
assert.equal(unsupported.iterations, "1");
assert.match(unsupported.answer, /Agent đã gọi tool/);
assert.match(unsupported.answer, /NY/);
assert.match(unsupported.feedback, /HN sang NY/);
assert.equal(unsupported.disabled, false);

const capped = clickRun(
  "Tìm cho tôi chuyến bay từ HAN đi SGN dưới 2 triệu, rồi cho biết thời tiết SGN nên mặc gì?",
  "2",
);
assert.equal(capped.status, "max_iterations_reached");
assert.equal(capped.iterations, "2");

console.log("UI click-path test: passed");
