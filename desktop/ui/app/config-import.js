// Configuration-file parser shared by the browser UI and focused Node tests.
//
// Owner support bundles are JSON (`{"config": {...}}`), while older Alpha POS
// exports use one KEY=VALUE setting per line. Keep both formats at this boundary
// and send only keys advertised by get_config() to the Python bridge.
function parseConfigImport(text, recognizedKeys) {
  const source = String(text == null ? "" : text).trim();
  if (!source) {
    return { ok: false, error: "The configuration file is empty." };
  }

  let candidate;
  if (source[0] === "{" || source[0] === "[") {
    let parsed;
    try {
      parsed = JSON.parse(source);
    } catch (error) {
      return { ok: false, error: "The configuration JSON is invalid." };
    }
    if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
      return { ok: false, error: "Expected a JSON configuration object." };
    }
    if (Object.prototype.hasOwnProperty.call(parsed, "config")) {
      if (!parsed.config || Array.isArray(parsed.config) || typeof parsed.config !== "object") {
        return { ok: false, error: "The JSON config field must be an object." };
      }
      candidate = parsed.config;
    } else {
      candidate = parsed;
    }
  } else {
    candidate = {};
    source.split(/\r?\n/).forEach((line) => {
      const value = line.trim();
      if (!value || value[0] === "#" || value.indexOf("=") < 0) return;
      const separator = value.indexOf("=");
      const key = value.slice(0, separator).trim();
      if (key) candidate[key] = value.slice(separator + 1).trim();
    });
  }

  const allowed = new Set(Array.isArray(recognizedKeys) ? recognizedKeys : []);
  const values = {};
  Object.keys(candidate).forEach((key) => {
    if (allowed.size === 0 || allowed.has(key)) values[key] = candidate[key];
  });
  if (Object.keys(values).length === 0) {
    return {
      ok: false,
      error: allowed.size
        ? "The file contains no recognized Alpha POS settings."
        : "The file contains no configuration settings.",
    };
  }
  return { ok: true, data: values };
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { parseConfigImport };
}
