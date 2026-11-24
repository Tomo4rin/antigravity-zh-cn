(() => {
  const SKIP_TAGS = new Set([
    "SCRIPT",
    "STYLE",
    "NOSCRIPT",
    "CODE",
    "PRE",
    "TEXTAREA",
    "INPUT",
    "SELECT",
    "OPTION",
    "SVG",
    "CANVAS"
  ]);

  const ATTR_NAMES = ["placeholder", "title", "aria-label"];
  const MAX_TEXT_LEN = 300;
  const DYNAMIC_RULES = [
    [/^Worked for (.+)$/, "用时 $1"],
    [/^Thinking for (.+)$/, "正在思考 $1"],
    [/^Thought for (.+)$/, "已思考 $1"],
    [/^Turn (\d+) of (\d+)$/, "第 $1 / $2 轮"],
    [/^Load older messages, showing (\d+) of (\d+)$/, "加载更早消息（显示 $1 / $2）"],
    [/^See (\d+) more$/, "展开其余 $1 项"],
    [/^Show (\d+) breakdowns?$/, "显示 $1 项明细"],
    [/^(\d+) tools?$/, "$1 个工具"],
    [/^Reading (.+)$/, "正在读取 $1"],
    [/^Running (.+)$/, "正在运行 $1"],
    [/^Send feedback as (.+)$/, "以 $1 身份提交反馈"],
    [/^Good to see you, ([^.]+)\. What's next\?$/, "你好，$1。接下来做什么？"],
    [/^Hey ([^,]+), what should we build today\?$/, "嗨 $1，今天我们构建点什么？"],
    [/^Project: (.+)$/, "项目：$1"],
    [/^Your plan: (.+)$/, "当前方案：$1"],
    [/^You have used some of your weekly limit, it will fully refresh in (.+)$/, "你已使用部分每周额度，将在 $1 后完全重置"],
    [/^You have used some of your five hour limit, it will fully refresh in (.+)$/, "你已使用部分 5 小时额度，将在 $1 后完全重置"]
  ];

  const state = (window.__agZhCn = window.__agZhCn || {
    version: "0.8.0",
    dict: {},
    originals: new WeakMap(),
    attrOriginals: new WeakMap(),
    missingQueue: new Set(),
    observer: null,
    scheduled: false,
    enabled: false
  });
  state.version = "0.8.0";
  if (!state.missingQueue) state.missingQueue = new Set();

  function isProtected(el) {
    if (!el || el.nodeType !== 1) return false;
    if (SKIP_TAGS.has(el.tagName)) return true;
    if (el.isContentEditable) return true;
    // 跳过代码块、终端输出及富文本正文容器，避免误译代码或用户对话内容
    if (
      el.closest(
        "pre, code, textarea, [contenteditable='true'], .xterm, .monaco-editor, [data-ag-zh-skip='1']"
      )
    ) {
      return true;
    }
    return false;
  }

  function lookup(raw, dict) {
    if (!raw || typeof raw !== "string") return null;
    const trimmed = raw.trim();
    if (!trimmed || trimmed.length > MAX_TEXT_LEN) return null;
    let hit = dict[trimmed];
    if (!hit) {
      for (const [pattern, tpl] of DYNAMIC_RULES) {
        if (pattern.test(trimmed)) {
          hit = trimmed.replace(pattern, tpl);
          break;
        }
      }
    }
    if (!hit) return null;
    const leading = raw.slice(0, raw.indexOf(trimmed));
    const trailing = raw.slice(raw.indexOf(trimmed) + trimmed.length);
    return leading + hit + trailing;
  }

  const UI_CONTROL_SELECTOR =
    "button, [role='button'], [role='menuitem'], [role='tab'], [role='option'], label, h1, h2, h3, h4, nav a, summary";

  function maybeCollectMissing(el, raw) {
    if (!raw || typeof raw !== "string") return;
    const t = raw.trim();
    if (!t || t.length < 2 || t.length > 100) return;
    if (/[\u4e00-\u9fff]/.test(t)) return;
    if (!/[A-Za-z]{2,}/.test(t)) return;
    if (/^([a-zA-Z]:\\|\/|https?:\/\/|#|@|\d+([.,]\d+)?%?$)/.test(t)) return;
    // 跳过常见文件名、扩展名、快捷键组合与邮箱，避免污染待翻译列表
    if (/^[^\s]+\.(py|js|mjs|cjs|ts|tsx|json|md|svg|png|jpg|bak|jsonl|txt|yml|yaml)(#L\d+)?$/i.test(t)) return;
    if (/^(Ctrl|Alt|Shift|Enter|Esc|Tab|Space)(\+[A-Za-z0-9]+)*$/i.test(t)) return;
    if (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(t)) return;
    if (el && (el.matches(UI_CONTROL_SELECTOR) || el.closest(UI_CONTROL_SELECTOR))) {
      state.missingQueue.add(t);
    }
  }

  function translateTextNode(node) {
    const parent = node.parentElement;
    if (!parent || isProtected(parent)) return 0;

    let orig = state.originals.get(node);
    if (orig === undefined) {
      orig = node.nodeValue;
    }
    const translated = lookup(orig, state.dict);
    if (!translated) {
      maybeCollectMissing(parent, orig);
      return 0;
    }

    if (!state.originals.has(node)) {
      state.originals.set(node, orig);
    }
    if (node.nodeValue !== translated) {
      node.nodeValue = translated;
      return 1;
    }
    return 0;
  }

  function translateElementAttrs(el) {
    if (!el || el.nodeType !== 1) return 0;
    // INPUT 仅允许翻译 placeholder / aria-label / title，不改 value
    if (
      el.tagName !== "INPUT" &&
      el.tagName !== "TEXTAREA" &&
      isProtected(el)
    ) {
      return 0;
    }

    let count = 0;
    let map = state.attrOriginals.get(el);
    for (const attr of ATTR_NAMES) {
      if (!el.hasAttribute(attr)) continue;
      const current = el.getAttribute(attr);
      const orig = map && attr in map ? map[attr] : current;
      const translated = lookup(orig, state.dict);
      if (!translated) continue;
      if (!map) {
        map = {};
        state.attrOriginals.set(el, map);
      }
      if (!(attr in map)) {
        map[attr] = orig;
      }
      if (current !== translated) {
        el.setAttribute(attr, translated);
        count += 1;
      }
    }
    return count;
  }

  function translateTree(root) {
    if (!root || !state.enabled) return 0;
    let changed = 0;

    if (root.nodeType === 3) {
      return translateTextNode(root);
    }
    if (root.nodeType === 1) {
      changed += translateElementAttrs(root);
      const walker = document.createTreeWalker(
        root,
        NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT
      );
      let cur = walker.nextNode();
      while (cur) {
        if (cur.nodeType === 3) {
          changed += translateTextNode(cur);
        } else if (cur.nodeType === 1) {
          changed += translateElementAttrs(cur);
        }
        cur = walker.nextNode();
      }
    }
    return changed;
  }

  function restoreTree(root) {
    if (!root) return 0;
    let restored = 0;
    const walker = document.createTreeWalker(
      root,
      NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT
    );
    let cur = walker.nextNode();
    while (cur) {
      if (cur.nodeType === 3 && state.originals.has(cur)) {
        const orig = state.originals.get(cur);
        if (cur.nodeValue !== orig) {
          cur.nodeValue = orig;
          restored += 1;
        }
        state.originals.delete(cur);
      } else if (cur.nodeType === 1 && state.attrOriginals.has(cur)) {
        const map = state.attrOriginals.get(cur);
        for (const [attr, orig] of Object.entries(map)) {
          if (cur.getAttribute(attr) !== orig) {
            cur.setAttribute(attr, orig);
            restored += 1;
          }
        }
        state.attrOriginals.delete(cur);
      }
      cur = walker.nextNode();
    }
    return restored;
  }

  function ensureObserver() {
    if (state.observer) return;
    state.observer = new MutationObserver((mutations) => {
      if (!state.enabled || state.scheduled) return;
      state.scheduled = true;
      requestAnimationFrame(() => {
        state.scheduled = false;
        if (!state.enabled) return;
        for (const m of mutations) {
          if (m.type === "characterData") {
            translateTextNode(m.target);
          } else if (m.type === "attributes" && m.target) {
            translateElementAttrs(m.target);
          } else if (m.addedNodes && m.addedNodes.length) {
            for (const n of m.addedNodes) {
              translateTree(n);
            }
          }
        }
      });
    });
    state.observer.observe(document.body || document.documentElement, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ATTR_NAMES
    });
  }

  state.apply = function (newDict) {
    state.dict = newDict || {};
    state.enabled = true;
    const changed = translateTree(document.body || document.documentElement);
    ensureObserver();
    return { status: "applied", changed, dictSize: Object.keys(state.dict).length };
  };

  state.restore = function () {
    state.enabled = false;
    if (state.observer) {
      state.observer.disconnect();
      state.observer = null;
    }
    const restored = restoreTree(document.body || document.documentElement);
    return { status: "restored", restored };
  };

  state.takeMissing = function () {
    const arr = Array.from(state.missingQueue);
    state.missingQueue.clear();
    return arr;
  };

  state.dumpTexts = function () {
    const out = new Set();
    const uiSelector =
      "button, [role='button'], [role='menuitem'], [role='tab'], [role='option'], label, h1, h2, h3, h4, nav a, summary";
    document.querySelectorAll(uiSelector).forEach((el) => {
      if (isProtected(el)) return;
      const txt = (el.innerText || "").trim();
      if (txt && txt.length <= 60 && !/[\u4e00-\u9fff]/.test(txt)) {
        out.add(txt);
      }
      for (const attr of ATTR_NAMES) {
        const val = (el.getAttribute(attr) || "").trim();
        if (val && val.length <= 60 && !/[\u4e00-\u9fff]/.test(val)) {
          out.add(val);
        }
      }
    });
    return Array.from(out).sort();
  };
})();
