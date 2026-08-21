document.addEventListener("DOMContentLoaded", function () {
  if (typeof mermaid === "undefined") {
    return;
  }

  const codeBlocks = new Set();
  const selectors = [
    ".listingblock code[data-lang='mermaid']",
    "pre code.language-mermaid",
    "pre code[data-lang='mermaid']"
  ];

  selectors.forEach(function (selector) {
    document.querySelectorAll(selector).forEach(function (code) {
      codeBlocks.add(code);
    });
  });

  codeBlocks.forEach(function (code) {
    const source = code.textContent;
    if (!source || !source.trim()) {
      return;
    }

    const container = document.createElement("div");
    container.className = "mermaid";
    container.textContent = source;

    const listingBlock = code.closest(".listingblock");
    if (listingBlock) {
      listingBlock.replaceWith(container);
      return;
    }

    const pre = code.closest("pre");
    if (pre) {
      pre.replaceWith(container);
      return;
    }

    code.replaceWith(container);
  });

  try {
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: "loose",
      theme: "base",
      themeVariables: {
          fontSize: "0.75rem",
      }
    });
    mermaid.run({
      querySelector: ".mermaid"
    });
  } catch (error) {
    console.error("Failed to render Mermaid diagrams", error);
  }
});
